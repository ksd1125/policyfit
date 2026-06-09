#!/usr/bin/env python3
"""금액 LLM 구조화 자동 재개 (한도 회복 감지).

Codex 사용 한도가 회복되면 남은 미처리 케이스를 자동으로 이어서 처리.
cron으로 주기 실행하면, 한도가 풀릴 때마다 조금씩 처리해 결국 100% 완성.

동작:
  1. 남은 미처리(캐시 < 전체, 또는 guarded 존재) 확인 → 없으면 즉시 종료
  2. Codex 한도 체크(1건 테스트) → 소진 상태면 종료(다음 cron 때 재시도)
  3. 회복됐으면 extract-amount-llm.py --mode all --workers 2 실행
  4. 캐시 → DB 반영(--apply) + guard 재적용

사용:
  python scripts/resume-amounts.py          # 1회 재개 시도
  python scripts/resume-amounts.py --status  # 진행 상황만 확인
"""
import json, sys, os, subprocess, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DB = ROOT / "outputs" / "policyfit-db.json"
CACHE = ROOT / "outputs" / "_amount_struct_cache.json"


CLASS_CACHE = ROOT / "outputs" / "_classify_cache.json"


def remaining_count():
    """LLM 미처리(캐시 없음 + guarded) 건수."""
    data = json.loads(DB.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    uncached = sum(1 for r in data if r["id"] not in cache)
    guarded = sum(1 for r in data if r.get("amountSource") == "guarded")
    return uncached, guarded, len(data), len(cache)


def class_remaining():
    """분류 LLM 미처리 건수."""
    data = json.loads(DB.read_text(encoding="utf-8"))
    cache = json.loads(CLASS_CACHE.read_text(encoding="utf-8")) if CLASS_CACHE.exists() else {}
    return sum(1 for r in data if r["id"] not in cache), len(cache)


def codex_alive():
    """Codex 한도 회복 여부 (1건 테스트)."""
    codex_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")
    out_file = str(ROOT / "outputs" / "_codex_alive.txt")
    if os.path.exists(out_file):
        os.remove(out_file)
    try:
        r = subprocess.run(
            [codex_path, "exec", "--skip-git-repo-check",
             "-c", "model_reasoning_effort=low", "-o", out_file, "-"],
            input="Reply: OK".encode("utf-8"),
            capture_output=True, timeout=120, shell=True)
        err = r.stderr.decode("utf-8", "replace")
        ok = os.path.exists(out_file) and "usage limit" not in err and "hit your" not in err
        if os.path.exists(out_file):
            os.remove(out_file)
        return ok
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    uncached, guarded, total, cached = remaining_count()
    cls_remain, cls_cached = class_remaining()
    print(f"금액: 캐시 {cached}/{total} | 미캐시 {uncached} | guarded {guarded}")
    print(f"분류: 캐시 {cls_cached}/{total} | 미캐시 {cls_remain}")

    if args.status:
        return

    if uncached == 0 and guarded == 0 and cls_remain == 0:
        print("✓ 금액·분류 모두 LLM 처리 완료 — 재개 불필요")
        return

    print("Codex 한도 확인 중...")
    if not codex_alive():
        print("⏳ 아직 한도 소진 상태 — 다음 실행 때 재시도")
        return

    print("✓ 한도 회복 — 재개 시작\n")
    # 1) 금액 미처리
    if uncached > 0 or guarded > 0:
        subprocess.run([PY, "scripts/extract-amount-llm.py", "--mode", "all", "--workers", "2"], cwd=str(ROOT))
        subprocess.run([PY, "scripts/extract-amount-llm.py", "--apply"], cwd=str(ROOT))
        subprocess.run([PY, "scripts/guard-unverified-amounts.py"], cwd=str(ROOT))
    # 2) 분류 미처리
    if cls_remain > 0:
        subprocess.run([PY, "scripts/classify-llm.py", "--workers", "2"], cwd=str(ROOT))
        subprocess.run([PY, "scripts/classify-llm.py", "--apply"], cwd=str(ROOT))

    uncached2, guarded2, _, cached2 = remaining_count()
    print(f"\n재개 후: 캐시 {cached2}/{total}건 | 미캐시 {uncached2} | guarded {guarded2}")
    if uncached2 == 0:
        print("✓ 전수 완료!")
        # 완료 시 Windows 예약 작업 자기 삭제 (있으면)
        try:
            subprocess.run(["schtasks", "/delete", "/tn", "PolicyFit-ResumeAmounts", "/f"],
                           capture_output=True, shell=True)
            print("  예약 작업 PolicyFit-ResumeAmounts 자동 해제")
        except Exception:
            pass


if __name__ == "__main__":
    main()
