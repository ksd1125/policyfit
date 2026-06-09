#!/usr/bin/env python3
"""거대 금액(100억+) 중 "당" 표기 없는 케이스 라벨 명확화.

라벨이 사용자에게 "내가 받는 한도"로 오해될 수 있는 경우:
  "4,020억원" → "총사업비 4,020억원"

원문에 1인 한도가 별도로 있으면 그것을 추출 (부분적으로), 없으면 총사업비 표기.
"""
import json, sys, re, importlib.util, shutil
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
    for md in [folder / "detail.md"] + sorted(folder.glob("*.md")):
        if md.exists() and md.name != "detail.md" or md.name == "detail.md":
            try: parts.append(md.read_text(encoding="utf-8", errors="replace"))
            except: pass
    return "\n\n".join(parts)


def label_value(label):
    if not label: return 0
    rn = re.sub(r"\s+", "", label)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원|조원)", rn)
    if not m: return 0
    units = {"조원": 1_000_000_000_000, "억원": 100_000_000,
             "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try:
        return int(float(m.group(1).replace(",", "")) * units[m.group(2)])
    except: return 0


def has_per(label):
    return bool(re.search(r"(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가)\s*당", label or ""))


# 원문에서 1인/1사 한도 찾기 (extract_per_applicant 재사용)
UNIT = r"(억\s*원|천\s*만\s*원|백\s*만\s*원|만\s*원)"
PER = r"(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가|투자\s*건)"
PER_PATTERN = re.compile(
    r"(?:" + PER + r")\s*당\s*(?:총|최대|한도|상한|약)?\s*(\d[\d,.]*)\s*" + UNIT
)


def find_per_applicant(text):
    matches = []
    for m in PER_PATTERN.finditer(text):
        raw = m.group(0).strip()
        if raw not in matches:
            matches.append(raw)
    if not matches:
        return None
    matches.sort(key=lambda r: label_value(r), reverse=True)
    return matches[0]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    if not args.dry:
        backup = DB.with_suffix(".json.fixbudget-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}\n")

    targets = [r for r in data
               if label_value(r.get("amountLabel") or "") >= 10_000_000_000
               and not has_per(r.get("amountLabel") or "")]
    print(f"대상: {len(targets)}건\n")

    per_found = 0
    total_marked = 0
    for r in targets:
        text = load_full_text(r["id"])
        per = find_per_applicant(text) if text else None
        old_lbl = r["amountLabel"]
        if per:
            new_lbl = per
            r["amountSub"] = (r.get("amountSub") or "") + ("; " if r.get("amountSub") else "") + f"총사업비 {old_lbl}"
            per_found += 1
            mark = "✓ 1인 한도 발견"
        else:
            new_lbl = f"총사업비 {old_lbl}"
            total_marked += 1
            mark = "▷ 총사업비 표기"
        print(f"  [{r['id']}] {mark}")
        print(f"    {old_lbl} → {new_lbl}")
        if not args.dry:
            r["amountLabel"] = new_lbl
            # amountValue도 1인 한도에 맞춰 갱신
            r["amountValue"] = label_value(new_lbl) if per else None

    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n=== 완료 ===")
        print(f"  1인 한도 발견 후 교체: {per_found}건")
        print(f"  총사업비 표기로 명확화: {total_marked}건")
        print(f"→ DB 저장")
    else:
        print(f"\n=== DRY-RUN ===")


if __name__ == "__main__":
    main()
