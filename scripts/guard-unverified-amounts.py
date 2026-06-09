#!/usr/bin/env python3
"""미검증 다중후보 금액 보수 처리 (안전망).

LLM 검증 안 된 케이스 중 amountSub에 여러 금액이 있는 것(제주 유형)은
규칙이 잘못된 값을 골랐을 위험이 큼. 잘못된 금액 노출보다 "공고 확인"이 안전.

이 처리는 임시 안전망 — 한도 회복 후 extract-amount-llm.py로 정밀화하면
LLM 값이 덮어씀(explicit_llm 등). rebuild-all 파이프라인에도 LLM 단계 뒤에 배치.

사용:
  python scripts/guard-unverified-amounts.py --dry
  python scripts/guard-unverified-amounts.py
"""
import json, sys, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))

    targets = []
    for r in data:
        src = r.get("amountSource") or ""
        if src.endswith("_llm"):
            continue  # LLM 검증됨 → 신뢰
        sub = r.get("amountSub") or ""
        if ";" in sub:  # 다중후보 = 위험
            targets.append(r)

    print(f"미검증 다중후보(보수 처리 대상): {len(targets)}건\n")
    for r in targets[:12]:
        print(f"  [{r['amountLabel']}] → '지원 규모는 공고 확인' | {r['title'][:35]}")
    if len(targets) > 12:
        print(f"  ... 외 {len(targets)-12}건")

    if not args.dry:
        backup = DB.with_suffix(".json.guard-bak")
        shutil.copy2(DB, backup)
        for r in targets:
            r["amountLabel"] = "지원 규모는 공고 확인"
            r["amountValue"] = None
            r["amountSub"] = ""
            r["amountSource"] = "guarded"
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {len(targets)}건 보수 처리 ({backup.name} 백업)")
        print("  한도 회복 후 extract-amount-llm.py로 정밀화하면 LLM 값이 덮어씀")
    else:
        print(f"\n=== DRY-RUN ===")


if __name__ == "__main__":
    main()
