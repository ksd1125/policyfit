#!/usr/bin/env python3
"""분류 규칙 보정 — 명백한 goals 오분류 정정 (매칭 정확도 개선).

사업 운영자금(fund)과 무관한 사업(주거/출산/보육/장례 등 개인복지성)이
goals=['fund']로 분류돼 "운영자금" 검색에 잘못 매칭되는 문제 보정.

목적문이 명확히 비사업 성격이면 fund를 제거.
정밀 전면 재분류는 한도 회복 후 LLM으로(별도).

사용:
  python scripts/fix-classification-rules.py --dry
  python scripts/fix-classification-rules.py
"""
import json, sys, re, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"

# 목적문에 이 키워드가 핵심이면 '사업 운영자금'이 아님 (개인복지성)
# 주의: "보육"(기업보육=인큐베이션 오탐), "임대료"(사업장 임대료 가능)는 제외
NON_BIZ_FUND = [
    "전세", "월세", "주거", "보증금", "기숙사",
    "출산급여", "양육", "육아",
    "장례", "장제", "생계비",
]
# 단, 이 단어가 함께 있으면 진짜 사업자금일 수 있어 보정 제외
BIZ_SIGNAL = ["운영자금", "경영안정", "시설자금", "창업자금", "긴급경영", "이차보전 융자",
              "정책자금", "육성자금", "발전자금"]


def is_non_biz_fund(r):
    """목적문 핵심이 비사업(개인복지)인데 fund로 분류됐는지."""
    if "fund" not in r.get("goals", []):
        return False
    purpose = r.get("purpose", "")
    title = r.get("title", "")
    # 목적문(사용자에게 보이는 핵심)에 비사업 키워드
    hit = next((k for k in NON_BIZ_FUND if k in purpose), None)
    if not hit:
        return False
    # 사업자금 신호가 강하면 제외 (오탐 방지)
    if any(b in purpose or b in title for b in BIZ_SIGNAL):
        return False
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    targets = []
    for r in data:
        hit = is_non_biz_fund(r)
        if hit:
            targets.append((r, hit))

    print(f"=== goals=fund 오분류 보정 ({len(targets)}건) ===\n")
    for r, hit in targets:
        new_goals = [g for g in r["goals"] if g != "fund"]
        print(f"  [{hit}] goals {r['goals']} → {new_goals or '(없음)'}")
        print(f"    {r['title'][:50]}")

    if not args.dry and targets:
        shutil.copy2(DB, DB.with_suffix(".json.classfix-bak"))
        for r, hit in targets:
            r["goals"] = [g for g in r["goals"] if g != "fund"]
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {len(targets)}건 보정, DB 저장 (classfix-bak 백업)")
    elif args.dry:
        print(f"\n=== DRY-RUN ===")
    else:
        print("보정 대상 없음")


if __name__ == "__main__":
    main()
