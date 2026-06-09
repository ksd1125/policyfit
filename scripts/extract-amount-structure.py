#!/usr/bin/env python3
"""금액 구조화 추출.

DB의 amount 필드를 다음 4가지로 분해:
  - amountTotal       : 사업 총예산 ("총사업비 4,020억원")
  - amountTargetCount : 대상자 수 ("60개사 내외")
  - amountPerApplicant: 1인 한도 (명시 또는 총액÷대상수 계산)
  - amountSource      : 1인 한도의 출처 (explicit/calculated/total_only/none)

원문(detail.md + 첨부 마크다운)에서 패턴 매칭으로 추출.

사용:
  python scripts/extract-amount-structure.py --dry       # 미리보기
  python scripts/extract-amount-structure.py             # 적용 + 백업
"""
import json, sys, re, shutil, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
MD_BASE = ROOT / "raw" / "markdown" / "20260601-224706"


def load_full_text(pbln_id):
    folder = MD_BASE / pbln_id
    if not folder.is_dir(): return ""
    parts = []
    detail = folder / "detail.md"
    if detail.exists():
        parts.append(detail.read_text(encoding="utf-8", errors="replace"))
    for md in sorted(folder.glob("*.md")):
        if md.name != "detail.md":
            try: parts.append(md.read_text(encoding="utf-8", errors="replace"))
            except: pass
    return "\n\n".join(parts)


# ─────────────────────────────────────────────
# 1) 금액 단위 → 원
# ─────────────────────────────────────────────
def label_value(label):
    if not label: return None
    rn = re.sub(r"\s+", "", label)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원|조원)", rn)
    if not m: return None
    units = {"조원": 1_000_000_000_000, "억원": 100_000_000,
             "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try:
        return int(float(m.group(1).replace(",", "")) * units[m.group(2)])
    except: return None


def fmt_won(v):
    if v is None: return ""
    if v >= 100_000_000:
        n = v / 100_000_000
        return f"{int(n) if n == int(n) else round(n, 1)}억원"
    if v >= 10_000:
        return f"{v // 10_000:,}만원"
    return f"{v:,}원"


# ─────────────────────────────────────────────
# 2) 1인 한도 추출 ("당" 패턴)
# ─────────────────────────────────────────────
UNIT_MONEY = r"(억\s*원|천\s*만\s*원|백\s*만\s*원|만\s*원)"
PER_KW = r"(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가|투자\s*건)"
PER_PATTERN = re.compile(
    r"(?:" + PER_KW + r")\s*당\s*(?:총|최대|한도|상한|약)?\s*(\d[\d,.]*)\s*" + UNIT_MONEY
)


def extract_per_applicant(text):
    """1인/1사 명시 한도. max 선택."""
    if not text: return None
    hits = []
    for m in PER_PATTERN.finditer(text):
        raw = m.group(0).strip()
        v = label_value(raw)
        if v: hits.append((raw, v))
    if not hits: return None
    hits.sort(key=lambda x: x[1], reverse=True)
    return {"label": hits[0][0], "value": hits[0][1]}


# ─────────────────────────────────────────────
# 3) 대상자 수 추출 (신호어 + 단위)
# ─────────────────────────────────────────────
# 단위 키워드: "개사"가 가장 신뢰. "명/인"은 자격조건 노이즈 큼.
COUNT_UNIT_STRONG = r"(?:개\s*사|개\s*기업|개\s*업체|개사|업체|업소|점포)"
COUNT_UNIT_WEAK = r"(?:명|인)"

# 강한 신호어 — "모집규모: N개사" 처럼 명시적 모집 규모 표현만 신뢰
# (단순 "N개사"는 은행 수/부문 수 등 노이즈가 많아 제외)
COUNT_SIGNAL_STRONG = (
    r"(?:모집\s*규모|선정\s*규모|지원\s*규모|모집\s*인원|선정\s*인원|"
    r"모집\s*기업|선정\s*기업|모집\s*업체|선정\s*업체|모집\s*대상|선정\s*대상|"
    r"지원\s*대상\s*규모|총\s*지원\s*규모)"
)
# 후행어 — "N개사 내외/선정" 형태
COUNT_SUFFIX = r"(?:내외|정도|이내|선정|선발|모집|지원)"

# 패턴: 강한 신호어가 있는 경우만 (오인 방지)
COUNT_PATTERNS = [
    # 1) "모집규모 : N개사" — 가장 신뢰
    rf"(?:{COUNT_SIGNAL_STRONG})\s*[:：]?\s*(?:약|총)?\s*(\d[\d,]*)\s*{COUNT_UNIT_STRONG}",
    # 2) "N개사 내외/선정" (후행어 명시) — 단, 노이즈 컨텍스트 제외
    rf"(\d[\d,]*)\s*{COUNT_UNIT_STRONG}\s*{COUNT_SUFFIX}",
    # 3) "모집규모 : N명" — 약한 단위도 강한 신호어 있으면 허용
    rf"(?:{COUNT_SIGNAL_STRONG})\s*[:：]?\s*(?:약|총)?\s*(\d[\d,]*)\s*{COUNT_UNIT_WEAK}\s*{COUNT_SUFFIX}?",
]

# 제외 컨텍스트 — 매출액/근로자수/은행/부문/표창 등은 대상수 아님
COUNT_EXCLUDE_CTX = re.compile(
    r"(?:종업원|상시\s*근로자|근로자\s*수|직원\s*수|고용\s*인원|대표자|담당자|"
    r"가족\s*수|구성원|평균\s*인원|매출액|연\s*매출|최근\s*\d+\s*년|"
    r"은행|부문|표창|포상|시상|도급|법인이|이상인|이상의)"
)
COUNT_EXCLUDE_SUFFIX = re.compile(r"(?:이하|미만|이상|초과|부문)")

# 사업유형 제외 — 융자/이차보전/보증/포상은 총액÷대상수가 무의미
TYPE_EXCLUDE_CALC = re.compile(
    r"(?:융자|이차\s*보전|이차보전|보증|대출|포상|표창|시상|상장|"
    r"운전자금|육성자금|경영안정자금|특례보증)"
)


def extract_target_count(text):
    """대상자 수. 강한 신호어 있는 매치만 신뢰."""
    if not text: return None
    candidates = []
    for tier, pat in enumerate(COUNT_PATTERNS):
        for m in re.finditer(pat, text):
            n_str = m.group(1).replace(",", "")
            try: n = int(n_str)
            except: continue
            if not (2 <= n <= 100_000):
                continue
            # 컨텍스트 제외 검사 (앞 40자)
            before = text[max(0, m.start() - 40):m.start()]
            after = text[m.end():m.end() + 20]
            if COUNT_EXCLUDE_CTX.search(before):
                continue
            if COUNT_EXCLUDE_SUFFIX.search(after):
                continue
            candidates.append((tier, n, m.group(0).strip()))

    if not candidates: return None
    candidates.sort(key=lambda x: (x[0], -x[1]))
    best_tier = candidates[0][0]
    same_tier = [c for c in candidates if c[0] == best_tier]
    best = max(same_tier, key=lambda x: x[1])
    # 라벨 텍스트 정제 — 숫자+단위만 깔끔하게
    cleaned = _clean_count_raw(best[2])
    return {"raw": cleaned, "value": best[1]}


def _clean_count_raw(raw):
    """'모집규모 : 총 36개사' → '36개사' 로 정제."""
    raw = re.sub(r"\s+", " ", raw).strip()
    # 숫자+단위 부분만 추출
    m = re.search(r"(\d[\d,]*)\s*(개\s*사|개\s*기업|개\s*업체|개사|업체|업소|점포|명|인)", raw)
    if m:
        num = m.group(1)
        unit = re.sub(r"\s+", "", m.group(2))
        # 후행어 보존 (내외/정도)
        suffix = ""
        tail = raw[m.end():].strip()
        sm = re.match(r"(내외|정도|이내)", tail)
        if sm:
            suffix = " " + sm.group(1)
        return f"{num}{unit}{suffix}"
    return raw


# ─────────────────────────────────────────────
# 4) 총사업비 추출 (기존 amountLabel에 "총사업비" prefix 있으면 그것)
# ─────────────────────────────────────────────
# 명시적 예산 라벨만 — "총 N억" 같은 광범위 패턴은 영업이익/매출액을 오인하므로 제외
TOTAL_PATTERNS = [
    r"지원\s*예산\s*[:：]?\s*(?:국비\s*)?(?:총\s*)?([\d,]+\.?\d*)\s*" + UNIT_MONEY,
    r"총\s*사업비\s*[:：]?\s*([\d,]+\.?\d*)\s*" + UNIT_MONEY,
    r"사업\s*예산\s*[:：]?\s*([\d,]+\.?\d*)\s*" + UNIT_MONEY,
    r"(?:예산|사업비)\s*규모\s*[:：]?\s*([\d,]+\.?\d*)\s*" + UNIT_MONEY,
    r"총\s*지원\s*규모\s*[:：]?\s*([\d,]+\.?\d*)\s*" + UNIT_MONEY,
    r"국비\s*[:：]?\s*(?:총\s*)?([\d,]+\.?\d*)\s*" + UNIT_MONEY,
]

# 명시 라벨 매칭 시 주변 노이즈 컨텍스트 제외 (영업이익/매출/자산)
TOTAL_EXCLUDE_CTX = re.compile(
    r"(?:영업\s*이익|매출액|매출\s*액|자산\s*총액|자본금|순이익|당기|"
    r"거래액|거래\s*규모|시가총액|연\s*매출)"
)


def extract_total_budget(text, existing_label):
    """총사업비. **원문 명시 예산 라벨만** 신뢰 (영업이익/매출 노이즈 차단).

    existing_label fallback은 제거 — build 단계 fallback 값이 부정확할 수 있음.
    """
    if not text: return None
    for pat in TOTAL_PATTERNS:
        for m in re.finditer(pat, text):
            # 노이즈 컨텍스트(영업이익 등) 근처면 스킵
            ctx = text[max(0, m.start() - 30):m.end() + 10]
            if TOTAL_EXCLUDE_CTX.search(ctx):
                continue
            mm = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원|조원)",
                           re.sub(r"\s+", "", m.group(0)))
            if not mm: continue
            label = f"{mm.group(1)}{mm.group(2)}"
            v = label_value(label)
            if v and v >= 1_000_000_000:  # 10억 이상만
                return {"label": label, "value": v}
    return None


# ─────────────────────────────────────────────
# 5) 통합 — DB 1건 처리
# ─────────────────────────────────────────────
def enrich_amount(record, text):
    """레코드의 금액 구조 채움. 4개 필드 반환."""
    per = extract_per_applicant(text)
    count = extract_target_count(text)
    total = extract_total_budget(text, record.get("amountLabel"))

    # 사업유형이 융자/이차보전/보증/포상이면 calculated 부적절
    title = record.get("title", "")
    is_calc_unsafe = bool(TYPE_EXCLUDE_CALC.search(title))

    # 1인 한도 결정
    if per:
        per_label = per["label"]
        per_value = per["value"]
        source = "explicit"
    elif total and count and count["value"] > 1 and not is_calc_unsafe:
        estimated = total["value"] // count["value"]
        # 합리성 검사 — 1인 한도가 50억 이상이면 대상수 추출 오류 가능성 큼
        if estimated >= 5_000_000_000:
            per_label = None
            per_value = None
            source = "total_only"
            count = None
        else:
            per_label = f"약 {fmt_won(estimated)} (총액÷대상수)"
            per_value = estimated
            source = "calculated"
    elif total:
        per_label = None
        per_value = None
        source = "total_only"
    else:
        per_label = None
        per_value = None
        source = "none"

    return {
        "amountTotal":             total["label"] if total else None,
        "amountTotalValue":        total["value"] if total else None,
        "amountTargetCount":       count["raw"] if count else None,
        "amountTargetCountValue":  count["value"] if count else None,
        "amountPerApplicant":      per_label,
        "amountPerApplicantValue": per_value,
        "amountSource":            source,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", help="특정 ID")
    ap.add_argument("--show", type=int, default=20, help="미리보기 건수")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    if not args.dry:
        backup = DB.with_suffix(".json.struct-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}\n")

    stats = {"explicit": 0, "calculated": 0, "total_only": 0, "none": 0}
    samples_calc = []
    samples_explicit = []

    for r in data:
        if args.only and r["id"] != args.only:
            continue
        text = load_full_text(r["id"])
        enrich = enrich_amount(r, text)
        stats[enrich["amountSource"]] += 1

        if enrich["amountSource"] == "calculated" and len(samples_calc) < args.show:
            samples_calc.append((r, enrich))
        if enrich["amountSource"] == "explicit" and len(samples_explicit) < 5:
            samples_explicit.append((r, enrich))

        if not args.dry:
            r.update(enrich)

    print("=== 추출 결과 분포 ===")
    n = sum(stats.values())
    for k, v in stats.items():
        print(f"  {k}: {v}건 ({v*100//n}%)")
    print()

    print(f"=== 계산형 샘플 ({len(samples_calc)}건) ===")
    for r, e in samples_calc:
        print(f"  [{r['id']}] {r['title'][:50]}")
        print(f"    총사업비: {e['amountTotal']} / 대상수: {e['amountTargetCount']}")
        print(f"    → 추정 1인 한도: {e['amountPerApplicant']}")
        print()

    print(f"=== 명시형 샘플 ===")
    for r, e in samples_explicit:
        print(f"  [{r['id']}] {r['title'][:50]}")
        print(f"    {e['amountPerApplicant']} (대상수 {e['amountTargetCount']}, 총 {e['amountTotal']})")

    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n→ DB 저장")


if __name__ == "__main__":
    main()
