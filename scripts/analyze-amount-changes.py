#!/usr/bin/env python3
"""금액 재추출 변화 분석.

fix-amounts.py 적용 전 변화 패턴 분류:
- 의도된 수정 (총예산 → 1인 한도): 액수 큰 폭 감소
- 동일 (잡힌 값 그대로)
- 단위 표기만 정리
- 신규 추출 (None → 값)
- 손실 (값 → None)
- 의심: 1인 한도였는데 다른 표현으로 바뀜
"""
import json, sys, re, importlib.util
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
    folder = MD_BASE / pbln_id
    if not folder.is_dir():
        return ""
    parts = []
    detail = folder / "detail.md"
    if detail.exists():
        parts.append(detail.read_text(encoding="utf-8", errors="replace"))
    for md in sorted(folder.glob("*.md")):
        if md.name == "detail.md":
            continue
        try:
            parts.append(md.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return "\n\n".join(parts)


def value_won(raw):
    if not raw: return None
    rn = re.sub(r"\s+", "", raw)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원)", rn)
    if not m: return None
    units = {"억원": 100_000_000, "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try:
        return int(float(m.group(1).replace(",", "")) * units[m.group(2)])
    except Exception:
        return None


def fmt_won(v):
    if not v: return "?"
    if v >= 1_000_000_000_000:
        return f"{v/1_000_000_000_000:.1f}조"
    if v >= 100_000_000:
        return f"{v//100_000_000}억"
    if v >= 10_000:
        return f"{v//10_000}만"
    return str(v)


def main():
    k = _load("k", "build-knowledge-db.py")
    data = json.loads(DB.read_text(encoding="utf-8"))

    buckets = {
        "동일": [],
        "단위표기정리": [],          # 값 동일, 표기만 정리
        "1인한도화_큰감소": [],       # 새 값이 기존의 1/10 이하 = 총예산→1인 한도
        "1인한도화_중감소": [],       # 1/2 ~ 1/10
        "소폭변화": [],              # 0.5x ~ 2x
        "큰증가_의심": [],           # 2x 이상 = 의심
        "신규추출": [],              # None → 값
        "손실": [],                  # 값 → None
        "원문없음": [],
    }

    for r in data:
        text = load_full_text(r["id"])
        if not text:
            buckets["원문없음"].append(r)
            continue
        new = k.extract_amount(text)
        old_label = r.get("amountLabel") or ""
        old_v = value_won(old_label)
        new_label = new["max"] if new else None
        new_v = value_won(new_label) if new_label else None

        # 카테고리
        if (new_label or "") == old_label:
            buckets["동일"].append(r)
        elif new_v is None and old_v:
            buckets["손실"].append((r, old_label, new_label))
        elif old_v is None and new_v:
            buckets["신규추출"].append((r, old_label, new_label))
        elif old_v and new_v:
            if old_v == new_v:
                buckets["단위표기정리"].append((r, old_label, new_label))
            else:
                ratio = new_v / old_v
                if ratio <= 0.1:
                    buckets["1인한도화_큰감소"].append((r, old_label, new_label, old_v, new_v))
                elif ratio <= 0.5:
                    buckets["1인한도화_중감소"].append((r, old_label, new_label, old_v, new_v))
                elif ratio >= 2:
                    buckets["큰증가_의심"].append((r, old_label, new_label, old_v, new_v))
                else:
                    buckets["소폭변화"].append((r, old_label, new_label, old_v, new_v))

    print("=== 금액 재추출 변화 분류 ===\n")
    for k_name, items in buckets.items():
        print(f"[{k_name}]: {len(items)}건")
    print()

    # 의심 케이스 표본 출력
    print("=== 큰 감소(총예산→1인한도화) 표본 10건 ===")
    for tup in buckets["1인한도화_큰감소"][:10]:
        r, ol, nl, ov, nv = tup
        print(f"  [{r['id']}] {r['title'][:40]}")
        print(f"    {ol} ({fmt_won(ov)}) → {nl} ({fmt_won(nv)})")
    print()

    print("=== 큰 증가(의심) 전체 ===")
    for tup in buckets["큰증가_의심"]:
        r, ol, nl, ov, nv = tup
        print(f"  [{r['id']}] {r['title'][:40]}")
        print(f"    {ol} ({fmt_won(ov)}) → {nl} ({fmt_won(nv)})")
    print()

    print("=== 손실(값 → None) 표본 5건 ===")
    for tup in buckets["손실"][:5]:
        r, ol, nl = tup
        print(f"  [{r['id']}] {r['title'][:40]}")
        print(f"    {ol} → (없음)")
    print()

    print("=== 큰 폭 안 줄었지만 여전히 거대(>1000억) — 추가 검토 필요 ===")
    huge = [r for r in data if value_won(r.get("amountLabel") or "") and value_won(r.get("amountLabel")) >= 100_000_000_000]
    for r in huge[:15]:
        print(f"  [{r['id']}] {r['title'][:50]}: {r['amountLabel']}")
    print(f"  ...총 {len(huge)}건")


if __name__ == "__main__":
    main()
