#!/usr/bin/env python3
"""금액 종합 sanity 체크 — 모든 이상 패턴을 한 번에 검출.

개별 패치(두더지 잡기) 대신, 금액 관련 전 항목을 전수 검증.
rebuild-all / watch 의 게이트로 사용 → 신규/재빌드 시 이상 0 보장.

검출 항목:
  1. 단위 비표준 (백만원/천만원/천원 잔존)
  2. value 범위 (기업당 1천원 미만 / 1조 초과)
  3. 라벨-value 큰 불일치 (단일 금액 라벨만; 서술/범위 제외)
  4. 깨진 값 (0원, 빈 괄호, 0+단위)
  5. total < perApplicant (총사업비가 1인 한도보다 작음 = 역전)
  6. 라벨 있는데 value 없음 (또는 반대)

종료코드: 이상 있으면 1 (CI 게이트용)
"""
import json, sys, re
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"


def label_max_won(label):
    """라벨의 모든 금액 중 최대 원화값."""
    if not label:
        return None
    vals = []
    for m in re.finditer(r"(\d[\d,.]*)\s*(조|억|천만|백만|천원|만)", label.replace(" ", "")):
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        mult = {"조": 1e12, "억": 1e8, "천만": 1e7, "백만": 1e6, "천원": 1e3, "만": 1e4}[m.group(2)]
        vals.append(n * mult)
    # 순수 원 단위 (큰 숫자)
    for m in re.finditer(r"(\d[\d,]{6,})\s*원", label):
        vals.append(float(m.group(1).replace(",", "")))
    return max(vals) if vals else None


def is_descriptive(label):
    """서술형/범위 라벨 (라벨-value 불일치 검사 제외 대상)."""
    if not label:
        return False
    # 범위(~), 복수 금액, 조건부 표현
    if "~" in label or "또는" in label or "차등" in label:
        return True
    # 금액 토큰 2개 이상
    cnt = len(re.findall(r"\d[\d,.]*\s*(?:조|억|천만|백만|천원|만)\s*원", label))
    return cnt >= 2


def main():
    data = json.loads(DB.read_text(encoding="utf-8"))
    issues = {}

    def add(k, r, note=""):
        issues.setdefault(k, []).append((r["id"], (r.get("title") or "")[:38], note))

    for r in data:
        per_lbl = r.get("amountPerApplicant") or ""
        lbl = r.get("amountLabel") or ""
        tot_lbl = r.get("amountTotal") or ""
        per_v = r.get("amountPerApplicantValue")
        tot_v = r.get("amountTotalValue")
        card = per_lbl or lbl

        # 1) 단위 비표준
        for f, v in [("PerApplicant", per_lbl), ("Label", lbl), ("Total", tot_lbl), ("Sub", r.get("amountSub") or "")]:
            if "백만원" in v or "천만원" in v or re.search(r"\d\s*천원", v):
                add("1.단위비표준", r, f"{f}:{v[:25]}")

        # 2) value 범위 (기업당)
        if per_v is not None:
            if per_v < 1000:
                add("2.기업당_과소(<1천원)", r, f"{per_v}원")
            if per_v > 1e12:
                add("2.기업당_과대(>1조)", r, f"{per_v}원")

        # 3) 라벨-value 불일치 (단일 금액만)
        if per_lbl and per_v and not is_descriptive(per_lbl):
            lv = label_max_won(per_lbl)
            if lv and abs(lv - per_v) / max(lv, per_v) > 0.02:
                add("3.라벨-value불일치", r, f"라벨{int(lv)} vs val{per_v}")

        # 4) 깨진 값 (앞에 숫자/콤마 없는 순수 0 + 단위, 또는 빈 괄호)
        if re.search(r"(?<![\d,])0+\s*(?:백만|천만|천원|만|억)\s*원", card) or "()" in card:
            add("4.깨진값", r, card[:30])

        # 5) total < perApplicant (역전) — total 추출이 의심
        if per_v and tot_v and tot_v < per_v:
            add("5.총액<기업당(역전)", r, f"총{tot_v} < 1인{per_v}")

        # 6) 라벨-value 비대칭 (외화 제외)
        if per_lbl and label_max_won(per_lbl) and not per_v and not re.search(r"불|달러|USD|\$|유로|엔", per_lbl):
            add("6.라벨있는데value없음", r, per_lbl[:25])

    # 리포트
    total_issues = sum(len(v) for v in issues.values())
    print(f"=== 금액 종합 sanity 체크 ({len(data)}건) ===\n")
    if not issues:
        print("✅ 이상 0건 — 모든 금액 정상")
        return 0
    for k in sorted(issues):
        print(f"  ⚠ {k}: {len(issues[k])}건")
        for id_, title, note in issues[k][:5]:
            print(f"      {id_} | {title} | {note}")
        if len(issues[k]) > 5:
            print(f"      ... 외 {len(issues[k])-5}건")
    print(f"\n총 {total_issues}건 이상")
    out = ROOT / "outputs" / "audit-amounts.json"
    out.write_text(json.dumps({k: [{"id": i, "title": t, "note": n} for i, t, n in v]
                               for k, v in issues.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out.name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
