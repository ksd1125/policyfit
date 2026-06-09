#!/usr/bin/env python3
"""정책핏 DB 전체 재빌드 오케스트레이터.

원본(raw/markdown) → 최종 policyfit-db.json 까지 모든 단계를 순서대로 실행.
각 단계는 캐시(LLM 결과)를 활용하므로 재빌드해도 누적된 품질이 보존됨.

단계:
  1. build-knowledge-db.py     원문 → knowledge-db (금액/대상/목적 추출)
  2. build-policyfit-db.py     knowledge → policyfit-db (UI 스키마)
  3. merge-purposes            목적문 캐시(Codex+Claude) 반영
  4. extract-amount-structure  금액 구조화 (explicit 규칙)
  5. extract-amount-llm --apply  LLM 금액 구조 캐시 반영 (규칙보다 우선)
  6. guard-unverified-amounts  미검증 다중후보 보수처리
  7. classify-llm --apply      LLM 분류 반영
  8. fix-classification-rules  분류 오류 규칙 보정
  9. fix-administrative-terms  맞춤법·행정용어 정제
  10. fix-budget-labels        거대 금액 "총사업비" 명확화
  11. normalize-amount-units   금액 단위 표준화(억원/만원)
  12. fix-data-issues          데이터 이슈 일괄정제
  13. preserve-external-notices 외부 신규공고 보존
  → verify: 금액 sanity 게이트 + 품질 리포트

사용:
  python scripts/rebuild-all.py            # 전체 재빌드
  python scripts/rebuild-all.py --from 3   # 3단계부터 (이미 빌드된 경우)
  python scripts/rebuild-all.py --dry      # 명령만 출력
"""
import sys, subprocess, argparse, json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

STEPS = [
    ("knowledge-db 빌드",      ["scripts/build-knowledge-db.py"]),
    ("policyfit-db 빌드",      ["scripts/build-policyfit-db.py"]),
    ("목적문 캐시 머지",        ["scripts/merge-purposes.py"]),
    ("금액 구조화(규칙)",       ["scripts/extract-amount-structure.py"]),
    ("금액 구조화(LLM)",        ["scripts/extract-amount-llm.py", "--apply"]),
    ("미검증 다중후보 보수처리",  ["scripts/guard-unverified-amounts.py"]),
    ("분류 LLM 반영",           ["scripts/classify-llm.py", "--apply"]),
    ("분류 오류 규칙 보정",      ["scripts/fix-classification-rules.py"]),
    ("맞춤법·용어 정제",        ["scripts/fix-administrative-terms.py", "--no-llm"]),
    ("거대금액 라벨 명확화",     ["scripts/fix-budget-labels.py"]),
    ("금액 단위 표준화",         ["scripts/normalize-amount-units.py"]),
    ("데이터 이슈 일괄정제",      ["scripts/fix-data-issues.py"]),
    ("외부 신규공고 보존",       ["scripts/preserve-external-notices.py"]),
]


def run_step(idx, name, cmd, dry):
    print(f"\n{'='*60}")
    print(f"[{idx}/{len(STEPS)}] {name}")
    print(f"  $ python {' '.join(cmd)}")
    print('='*60)
    if dry:
        return True
    result = subprocess.run([PY] + cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n❌ 단계 {idx} 실패 (exit {result.returncode})")
        return False
    return True


def verify():
    """최종 검증 리포트."""
    import importlib.util, subprocess
    # 금액 종합 sanity 게이트
    print("\n[게이트] 금액 sanity 체크...")
    subprocess.run([PY, "scripts/audit-amounts.py"], cwd=str(ROOT))
    db = json.loads((ROOT / "outputs" / "policyfit-db.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("sp", ROOT / "scripts" / "score-purposes.py")
    sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)

    scores = [sp.score_purpose(r.get("purpose", ""))[0] for r in db]
    avg = sum(scores) / len(scores)
    a = sum(1 for s in scores if s >= 85)

    from collections import Counter
    src = Counter(r.get("amountSource") or "legacy" for r in db)

    print(f"\n{'='*60}")
    print("최종 검증")
    print('='*60)
    print(f"  레코드: {len(db)}건")
    print(f"  목적문 평균: {avg:.1f}점 (A등급 {a}/{len(db)} = {a*100//len(db)}%)")
    print(f"  금액 출처 분포:")
    for k, v in src.most_common():
        print(f"    {k}: {v}건")
    # 거대금액 잔존 검사
    import re
    def lv(l):
        if not l: return 0
        m = re.search(r"(\d[\d,.]*)억원", re.sub(r"\s+", "", l))
        return int(float(m.group(1).replace(",", "")) * 1e8) if m else 0
    huge = [r for r in db if lv(r.get("amountPerApplicant") or r.get("amountLabel") or "") >= 10_000_000_000
            and "총사업비" not in (r.get("amountLabel") or "")
            and not re.search(r"당", r.get("amountPerApplicant") or r.get("amountLabel") or "")]
    print(f"  ⚠ 거대금액 미해결(100억+, 당/총사업비 없음): {len(huge)}건")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1, help="시작 단계")
    ap.add_argument("--to", dest="end", type=int, default=len(STEPS), help="종료 단계")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    print("정책핏 DB 전체 재빌드")
    print(f"단계 {args.start}~{args.end} / 총 {len(STEPS)}")

    for idx, (name, cmd) in enumerate(STEPS, 1):
        if idx < args.start or idx > args.end:
            continue
        ok = run_step(idx, name, cmd, args.dry)
        if not ok:
            sys.exit(1)

    if not args.dry and args.end >= len(STEPS):
        verify()
    print("\n✓ 완료")


if __name__ == "__main__":
    main()
