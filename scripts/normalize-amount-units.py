#!/usr/bin/env python3
"""금액 단위 표준화 — 억원/만원 2단위 통일.

규칙:
  - 1억 이상 → "N억원" (정수) / "N.N억원" (천만 단위) / "N억 N,NNN만원" (복합)
  - 1만~1억 미만 → "N,NNN만원"
  - 1만 미만 → "N원" 유지
  - 백만원/천만원 같은 비표준 표기 제거 (30백만원→3,000만원, 9.9천만원→9,900만원)

라벨 텍스트의 금액 토큰만 치환 (접두 "최대/업체당", 접미 "이내/이하" 유지).
value 필드는 라벨 대표 금액으로 재계산.

사용:
  python scripts/normalize-amount-units.py --dry
  python scripts/normalize-amount-units.py
"""
import json, sys, re, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"

# 금액 토큰 패턴 (복합 우선: 조+억+천만+백만+만+천원)
AMOUNT_RE = re.compile(
    r"\d[\d,.]*\s*조(?:\s*\d[\d,.]*\s*천억)?(?:\s*\d[\d,.]*\s*억)?(?:\s*\d[\d,.]*\s*천만)?(?:\s*\d[\d,.]*\s*만)?\s*원?"
    r"|\d[\d,.]*\s*천\s*억\s*원"
    r"|\d[\d,.]*\s*억(?:\s*\d[\d,.]*\s*천만)?(?:\s*\d[\d,.]*\s*백만)?(?:\s*\d[\d,.]*\s*만)?\s*원?"
    r"|\d[\d,.]*\s*천\s*만\s*원"
    r"|\d[\d,.]*\s*백\s*만\s*원"
    r"|\d[\d,.]*\s*천\s*원"   # 천원 단위 (예: 4,000천원 = 400만원)
    r"|\d[\d,.]*\s*만\s*원"
    r"|\d[\d,]{6,}\s*원"      # 순수 원 단위 7자리+ (예: 40,000,000원)
)


def token_to_won(tok):
    t = tok.replace(",", "").replace(" ", "")
    won = 0.0
    used = False
    # 큰 단위부터 매칭하며 소비 (천만/천원 구분 위해 매칭부 제거)
    for pat, mult in [(r"([\d.]+)조", 1e12), (r"([\d.]+)천억", 1e11), (r"([\d.]+)억", 1e8),
                      (r"([\d.]+)천만", 1e7), (r"([\d.]+)백만", 1e6),
                      (r"([\d.]+)만", 1e4), (r"([\d.]+)천원", 1e3)]:
        m = re.search(pat, t)
        if m:
            won += float(m.group(1)) * mult
            t = t[:m.start()] + t[m.end():]   # 소비 (천만 소비 후 천원 구분)
            used = True
    if not used:                       # 순수 원 단위
        m = re.fullmatch(r"(\d+)원?", t)
        if m:
            won = float(m.group(1)); used = True
    return int(round(won)) if used else 0


def fmt_won(won):
    # 조 단위 (총사업비 거대값)
    if won >= 1e12:
        if won % 1e12 == 0:
            return f"{int(won // 1e12):,}조원"
        eok = int((won % 1e12) // 1e8)
        return f"{int(won // 1e12):,}조 {eok:,}억원"
    if won >= 1e8:
        if won % 1e8 == 0:
            return f"{int(won // 1e8):,}억원"
        if won % 1e7 == 0 and won < 1e9:   # 10억 미만 천만단위 → 소수1자리
            return f"{won / 1e8:.1f}억원"
        eok = int(won // 1e8)              # 복합
        man = int((won % 1e8) // 1e4)
        return f"{eok:,}억 {man:,}만원"
    if won >= 1e4:
        if won % 1e4 == 0:
            return f"{int(won // 1e4):,}만원"
        return f"{int(won):,}원"        # 만원 미만 잔액 → 원 유지 (445,000원)
    return f"{int(won):,}원"


def normalize_label(label):
    if not label:
        return label
    def repl(m):
        won = token_to_won(m.group(0))
        if won > 0:
            return fmt_won(won)
        # 깨진 0값(00백만원 등)은 제거
        if re.match(r"0+\s*(?:백만|천만|만|억)?\s*원", m.group(0).replace(",", "")):
            return ""
        return m.group(0)
    s = AMOUNT_RE.sub(repl, label)
    # 빈 항목·구분자 정리
    s = re.sub(r";\s*;", ";", s)
    s = re.sub(r"^\s*;\s*|\s*;\s*$", "", s)
    # 한글 금액 부연 괄호 제거 (예: "4,000만원(사천만원)" → "4,000만원")
    s = re.sub(r"\s*\([일이삼사오육칠팔구십백천만억조\s]+원\)", "", s)
    s = re.sub(r"\(\s*\)", "", s)          # 빈 괄호
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def rep_value(label):
    """라벨의 대표(최대) 금액 원화값."""
    if not label:
        return None
    vals = [token_to_won(m.group(0)) for m in AMOUNT_RE.finditer(label)]
    vals = [v for v in vals if v]
    return max(vals) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    changes = []

    for r in data:
        for f in ["amountPerApplicant", "amountLabel", "amountTotal", "amountSub", "benefits"]:
            old = r.get(f)
            if not old:
                continue
            new = normalize_label(old)
            if new != old:
                changes.append((f, old, new))
                if not args.dry:
                    r[f] = new
        if not args.dry:
            # 빈 라벨(깨진 0값 정리 결과)은 공고 확인으로
            for f in ["amountPerApplicant", "amountLabel"]:
                if f in r and r.get(f) is not None and not str(r[f]).strip():
                    r[f] = None if f == "amountPerApplicant" else "지원 규모는 공고 확인"
            if r.get("amountSub") is not None and not str(r["amountSub"]).strip():
                r["amountSub"] = ""
            # value 필드 라벨 기준 재계산
            if r.get("amountPerApplicant"):
                v = rep_value(r["amountPerApplicant"])
                if v: r["amountPerApplicantValue"] = v
            if r.get("amountLabel"):
                v = rep_value(r["amountLabel"])
                if v: r["amountValue"] = v
            if r.get("amountTotal"):
                v = rep_value(r["amountTotal"])
                if v: r["amountTotalValue"] = v
            # 역전 정리: 총사업비 < 기업당 한도 = total이 다른 차원(이차보전 예산 등) → 제거
            pv = r.get("amountPerApplicantValue")
            tv = r.get("amountTotalValue")
            if pv and tv and tv < pv:
                r["amountTotal"] = None
                r["amountTotalValue"] = None

    print(f"=== 금액 단위 표준화 ({len(changes)}건 변경) ===\n")
    # 단위별 샘플
    shown = 0
    for f, old, new in changes:
        if shown < 25:
            print(f"  {old[:38]}  →  {new[:38]}")
            shown += 1
    if len(changes) > 25:
        print(f"  ... 외 {len(changes)-25}건")

    if not args.dry:
        shutil.copy2(DB, DB.with_suffix(".json.unitfix-bak"))
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ DB 저장 (unitfix-bak 백업)")
    else:
        print(f"\n=== DRY-RUN ===")


if __name__ == "__main__":
    main()
