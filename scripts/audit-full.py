#!/usr/bin/env python3
"""정책핏 DB 종합 오류 진단 (전수, 패턴 기반).

매건 수동 검증 대신, 오류 '패턴'을 규칙으로 검출해 일괄 발견.
6개 영역: 무결성 / 목적문 / 금액 / 대상·자격 / 기간·링크 / 일관성
결과는 콘솔 요약 + outputs/audit-full.json (상세).
"""
import json, sys, re
from pathlib import Path
from datetime import date
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
OUT = ROOT / "outputs" / "audit-full.json"

REQUIRED = ["id", "title", "purpose", "amountLabel", "period", "match", "url"]


def won(label):
    if not label: return 0
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원)", re.sub(r"\s+", "", label))
    if not m: return 0
    u = {"억원": 1e8, "천만원": 1e7, "백만원": 1e6, "만원": 1e4}
    try: return int(float(m.group(1).replace(",", "")) * u[m.group(2)])
    except: return 0


def main():
    data = json.loads(DB.read_text(encoding="utf-8"))
    N = len(data)
    issues = {}

    def add(key, r, note=""):
        issues.setdefault(key, []).append({"id": r["id"], "title": r["title"][:45], "note": note})

    today = date.today().isoformat()

    for r in data:
        # ── 1. 무결성 ──
        for f in REQUIRED:
            if f not in r or r[f] in (None, ""):
                add("무결성:필수필드누락", r, f)
        # 깨진 인코딩 흔적
        for f in ("title", "purpose"):
            if r.get(f) and ("�" in r[f] or "�" in r[f]):
                add("무결성:깨진문자", r, f)

        # ── 2. 목적문 ──
        p = r.get("purpose", "") or ""
        if p:
            if len(p) < 25:
                add("목적문:너무짧음", r, f"{len(p)}자")
            if len(p) > 140:
                add("목적문:너무김", r, f"{len(p)}자")
            if not p.rstrip().endswith(("요.", "요", "에요.", "예요.")):
                add("목적문:종결어미이상", r, p[-12:])
            # 관공서/법령 잔재
            if re.search(r"합니다\.?$|입니다\.?$|「.*법", p):
                add("목적문:관공서체잔재", r, p[-15:])
            # 대상자 설명을 목적으로 오인 (예: "~인 기업")
            if re.match(r"^.{0,12}(에 소재|에 등록|을 영위|를 영위)", p):
                add("목적문:대상혼동", r, p[:30])

        # ── 3. 금액 ──
        src = r.get("amountSource") or "none"
        card = r.get("amountPerApplicant") or r.get("amountLabel") or ""
        if not src.endswith("_llm") and src != "guarded":
            # 미검증
            if r.get("amountSub") and ";" in r["amountSub"]:
                add("금액:미검증다중후보", r, card)
        # 거대금액인데 1인/총사업비/보증 표기 없음 (LLM검증 제외)
        if won(card) >= 1e10 and not any(k in card for k in ["당", "총사업비", "보증", "공고 확인"]):
            add("금액:거대미표기", r, card)
        # 0원/이상값
        if card and won(card) and won(card) < 10000:
            add("금액:이상저액", r, card)

        # ── 4. 대상·자격 ──
        if not r.get("targetShort") and not r.get("targetDetail"):
            add("대상:누락", r)

        # ── 5. 기간·링크 ──
        end = r.get("endDate")
        if end and end < today:
            add("기간:만료", r, end)
        url = r.get("url", "")
        if url and not re.match(r"https?://", url):
            add("링크:형식이상", r, url[:30])

        # ── 6. 매칭 ──
        m = r.get("match")
        if m is None or not (0 <= (m or 0) <= 100):
            add("매칭:범위이상", r, str(m))

    # ── 리포트 ──
    print(f"=== 종합 진단 ({N}건) ===\n")
    cats = {}
    for k, v in sorted(issues.items()):
        area = k.split(":")[0]
        cats.setdefault(area, 0)
        cats[area] += len(v)
        sev = "🔴" if area in ("무결성",) else ("🟡" if area in ("목적문", "금액") else "⚪")
        print(f"  {sev} {k}: {len(v)}건")
    print()
    print("=== 영역별 합계 ===")
    for a, c in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {a}: {c}건")

    # 샘플 (주요 이슈)
    print("\n=== 주요 이슈 샘플 ===")
    for k in ["무결성:필수필드누락", "무결성:깨진문자", "목적문:관공서체잔재",
              "목적문:대상혼동", "목적문:종결어미이상", "금액:거대미표기", "금액:이상저액"]:
        if k in issues:
            print(f"\n[{k}] {len(issues[k])}건")
            for it in issues[k][:4]:
                print(f"  {it['id']} | {it['title']} | {it['note']}")

    OUT.write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 상세: {OUT.name}")


if __name__ == "__main__":
    main()
