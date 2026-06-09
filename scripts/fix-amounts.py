#!/usr/bin/env python3
"""금액 필드 surgical 재추출.

**보수 전략**: 원문에 "업체당/기업당/N당" 같은 1인 기준 표기가 **명시된 경우만** 교체.
그 외(원문이 모호하거나 한도/총액 구분 어려운 경우)는 기존 값 유지.

전체 빌드 없이 detail.md + 첨부 마크다운을 다시 읽어 갱신.
목적문 캐시·다른 필드는 손대지 않음.

사용:
  python scripts/fix-amounts.py --dry         # 변경 미리보기
  python scripts/fix-amounts.py               # 적용 + 백업
  python scripts/fix-amounts.py --only PBLN_xxx  # 특정 ID만
"""
import json, sys, re, importlib.util, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
MD_BASE = ROOT / "raw" / "markdown" / "20260601-224706"


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def load_full_text(pbln_id):
    """공고 폴더에서 detail.md + 첨부 마크다운 모두 합쳐 반환."""
    folder = MD_BASE / pbln_id
    if not folder.is_dir():
        return ""
    parts = []
    detail = folder / "detail.md"
    if detail.exists():
        parts.append(detail.read_text(encoding="utf-8", errors="replace"))
    # 첨부 마크다운들
    for md in sorted(folder.glob("*.md")):
        if md.name == "detail.md":
            continue
        try:
            parts.append(md.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return "\n\n".join(parts)


def parse_value(raw):
    """'200억원' → 20000000000 (정수). 없으면 None."""
    if not raw:
        return None
    rn = re.sub(r"\s+", "", raw)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원)", rn)
    if not m:
        return None
    units = {"억원": 100_000_000, "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try:
        num = float(m.group(1).replace(",", ""))
        return int(num * units[m.group(2)])
    except Exception:
        return None


# "당" 패턴만 — 1인/1사 기준 명시 케이스 추출용
UNIT = r"(억\s*원|천\s*만\s*원|백\s*만\s*원|만\s*원)"
PER = r"(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가|투자\s*건|사업)"
PER_PATTERN = re.compile(
    r"(?:" + PER + r")\s*당\s*(?:총|최대|한도|상한|약)?\s*(\d[\d,.]*)\s*" + UNIT
)


def extract_per_applicant(text):
    """1인/1사 기준 한도만 추출. 매칭되면 max 선택, 없으면 None."""
    matches = []
    for m in PER_PATTERN.finditer(text):
        raw = m.group(0).strip()
        if raw not in matches:
            matches.append(raw)
    if not matches:
        return None
    matches.sort(key=lambda r: parse_value(r) or 0, reverse=True)
    return {"max": matches[0], "raw": "; ".join(matches[:3])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", help="특정 공고 ID만")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))

    if not args.dry:
        backup = DB.with_suffix(".json.fixamt-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}\n")

    changed = []
    no_change = 0
    no_text = 0

    for r in data:
        if args.only and r["id"] != args.only:
            continue
        text = load_full_text(r["id"])
        if not text:
            no_text += 1
            continue

        # "당" 패턴 명시 케이스만 교체. 그 외 기존 값 유지(보수적).
        new = extract_per_applicant(text)
        if not new:
            no_change += 1
            continue

        new_label = new["max"]
        new_value = parse_value(new["max"])
        new_sub = new["raw"] if new["raw"] != new["max"] else ""

        old_label = r.get("amountLabel") or ""
        old_value = r.get("amountValue")
        old_sub = r.get("amountSub") or ""

        if (new_label, new_value, new_sub) == (old_label, old_value, old_sub):
            no_change += 1
            continue

        changed.append({
            "id": r["id"],
            "title": r["title"][:50],
            "old": (old_label, old_sub, old_value),
            "new": (new_label, new_sub, new_value),
        })
        if not args.dry:
            r["amountLabel"] = new_label
            r["amountValue"] = new_value
            r["amountSub"] = new_sub

    # 보고
    print(f"=== 금액 재추출 결과 ===")
    print(f"  변경: {len(changed)}건")
    print(f"  유지: {no_change}건")
    print(f"  원문 없음: {no_text}건")
    print()

    # 변경 큰 것 위주로 샘플 출력
    for c in changed[:50]:
        old_v = c["old"][2] or parse_value(c["old"][0]) or 0
        new_v = c["new"][2] or 0
        delta = ""
        if old_v and new_v:
            ratio = new_v / old_v
            if ratio < 0.1:
                delta = "  ⬇⬇ 대폭 축소 (총예산→1인 한도)"
            elif ratio < 0.5:
                delta = "  ⬇ 축소"
            elif ratio > 2:
                delta = "  ⬆ 증가"
        print(f"[{c['id']}] {c['title']}")
        print(f"  전: {c['old'][0]} (sub: {c['old'][1] or '-'})")
        print(f"  후: {c['new'][0]} (sub: {c['new'][1] or '-'}){delta}")
        print()

    if len(changed) > 30:
        print(f"... 외 {len(changed)-30}건 더\n")

    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("→ DB 저장")


if __name__ == "__main__":
    main()
