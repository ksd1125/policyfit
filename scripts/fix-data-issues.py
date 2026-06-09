#!/usr/bin/env python3
"""오류 탐지 에이전트가 발견한 데이터 이슈 일괄 정제 (규칙 기반).

처리:
  1. 레거시 amountLabel/amountValue ↔ 신규 amountPerApplicant 동기화 (모순 해소)
  2. 관광객 유치 인센티브: category=판로·마케팅, targetShort=여행사 통일
  3. goals 'digital' 과다 태깅 제거 (디지털 신호 전무한 융자/수수료)
  4. 결측 필드 보강 (benefits 빈값, targetDetail 빈값)

사용:
  python scripts/fix-data-issues.py --dry
  python scripts/fix-data-issues.py
"""
import json, sys, re, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"

DIGITAL_KW = ["디지털", "스마트", "키오스크", "배달", "온라인", "정보화", "클라우드",
              "AI", "인공지능", "빅데이터", "자동화", "이커머스", "플랫폼", "DX", "메타버스",
              "IoT", "사물인터넷", "실감", "가명정보", "데이터", "비대면", "무인",
              "VR", "AR", "XR", "핀테크", "ICT", "정보통신", "소프트웨어", "SW", "앱",
              "보안", "취약점", "침해", "정보보호", "사이버"]
TOURISM_KW = ["단체관광객 유치", "관광객 유치", "숙박관광객 유치", "관광 유치"]

# 빈 goals 발생 시 category 기반 fallback goal (개인복지성 제외)
CAT_GOAL = {"운영자금": "fund", "시설·환경": "fund", "안전망·세제": "fund",
            "교육·컨설팅": "fund", "창업 지원": "startup", "재기·재도전": "startup",
            "판로·마케팅": "sales", "수출·해외진출": "sales",
            "디지털 전환": "digital", "고용·인건비": "hr"}
NONBIZ_KW = ["주거", "전세", "월세", "출산", "양육", "육아", "보육료", "생계"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    stats = {"레거시동기화": 0, "관광분류": 0, "digital제거": 0, "goals보강": 0, "benefits보강": 0, "targetDetail보강": 0}

    for r in data:
        title = r.get("title", "")
        purpose = r.get("purpose", "")
        benefits = r.get("benefits") or ""
        blob = f"{title} {purpose} {benefits}"

        # 1) 레거시 금액 동기화 — perApplicant 있으면 label/value 일치
        per = r.get("amountPerApplicant")
        if per:
            pv = r.get("amountPerApplicantValue")
            if r.get("amountLabel") != per:
                r["amountLabel"] = per
                stats["레거시동기화"] += 1
            if pv is not None:
                r["amountValue"] = pv

        # 2) 관광객 유치 인센티브 분류 보정
        if any(k in title for k in TOURISM_KW):
            if r.get("category") != "판로·마케팅":
                r["category"] = "판로·마케팅"
                stats["관광분류"] += 1
            # 실수혜자는 여행사
            if "여행" in (r.get("targetDetail") or "") or "여행사" in title or "여행업" in (r.get("targetDetail") or ""):
                if r.get("targetShort") != "여행사":
                    r["targetShort"] = "여행사"

        # 3) digital 과다 태깅 제거 (디지털 신호 전무)
        if "digital" in r.get("goals", []):
            if not any(k in blob for k in DIGITAL_KW):
                r["goals"] = [g for g in r["goals"] if g != "digital"]
                stats["digital제거"] += 1

        # 3-1) 빈 goals → category fallback (개인복지성은 의도적 유지)
        if not r.get("goals") and not any(k in blob for k in NONBIZ_KW):
            g = CAT_GOAL.get(r.get("category"))
            if g:
                r["goals"] = [g]
                stats["goals보강"] += 1

        # 4) 결측 보강
        if not (r.get("benefits") or "").strip():
            # 지원내용 없으면 대상/목적 기반 안내
            r["benefits"] = (r.get("targetDetail") or r.get("targetShort") or "지원내용은 공고 확인")[:200]
            stats["benefits보강"] += 1
        if not (r.get("targetDetail") or "").strip():
            ts = r.get("targetShort")
            if ts:
                r["targetDetail"] = ts
                stats["targetDetail보강"] += 1

    print("=== 데이터 이슈 일괄 정제 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}건")

    if not args.dry:
        shutil.copy2(DB, DB.with_suffix(".json.datafix-bak"))
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n→ DB 저장 (datafix-bak 백업)")
    else:
        print("\n=== DRY-RUN ===")


if __name__ == "__main__":
    main()
