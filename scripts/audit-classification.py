#!/usr/bin/env python3
"""분류(goals/tags/category) 오류 전수 진단.

목적문·제목의 키워드와 분류가 불일치하는 패턴을 검출.
매칭 정확도의 근본 = 분류 정확도.
"""
import json, sys, re
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"

# 목적/내용 키워드 → 기대 성격
HOUSING = ["주거", "전세", "월세", "임대료", "보증금", "주택", "기숙사", "거주"]
NOT_BIZ = ["출산", "양육", "보육", "결혼", "장례", "의료비", "생계", "청년 정착", "귀농", "귀촌"]
# fund(자금)은 사업 운영/시설/창업 자금이어야
FUND_OK = ["운영자금", "융자", "대출", "보증", "경영안정", "시설자금", "창업자금", "긴급경영", "이차보전", "정책자금"]


def main():
    data = json.loads(DB.read_text(encoding="utf-8"))
    issues = {}

    def add(k, r, note=""):
        issues.setdefault(k, []).append((r["id"], r["title"][:42], note))

    for r in data:
        text = (r.get("purpose", "") + " " + r.get("title", "") + " " + (r.get("benefits") or ""))
        goals = r.get("goals", [])
        tags = r.get("tags", [])
        cat = r.get("category", "")

        # 1) 주거/비사업 키워드인데 fund 분류
        if any(k in text for k in HOUSING) and "fund" in goals:
            if not any(k in text for k in FUND_OK):
                add("주거→fund오분류", r, cat)
        # 2) 비사업(출산/양육 등) 키워드인데 사업자금 분류
        if any(k in text for k in NOT_BIZ) and "fund" in goals:
            if not any(k in text for k in FUND_OK):
                add("비사업→fund오분류", r, cat)
        # 3) 전업종 태그(6종) = 무차별 매칭
        if len(tags) >= 6:
            add("전업종태그", r, f"{len(tags)}종")
        # 4) goals 비어있음
        if not goals:
            add("goals누락", r)

    print(f"=== 분류 오류 진단 ({len(data)}건) ===\n")
    for k, v in sorted(issues.items(), key=lambda x: -len(x[1])):
        print(f"  {k}: {len(v)}건")
    print()

    for k in ["주거→fund오분류", "비사업→fund오분류"]:
        if k in issues:
            print(f"[{k}] 샘플:")
            for id_, t, note in issues[k][:6]:
                print(f"  {id_} | {t} | cat={note}")
            print()

    # 전업종 태그 비율
    if "전업종태그" in issues:
        print(f"전업종 태그(6종) {len(issues['전업종태그'])}건 = 전체의 {len(issues['전업종태그'])*100//len(data)}%")
        print("  → 업종 필터가 사실상 무력화될 수 있음")

    (ROOT / "outputs" / "audit-classification.json").write_text(
        json.dumps({k: [{"id": i, "title": t, "note": n} for i, t, n in v] for k, v in issues.items()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ outputs/audit-classification.json")


if __name__ == "__main__":
    main()
