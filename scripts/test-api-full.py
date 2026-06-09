#!/usr/bin/env python3
"""API 신규 공고에 '전체 분류 체인'을 적용해 테스트.

목적문만이 아니라 유형분류·지원규모·자격요건까지 전부 적용:
  API summary
    → build-knowledge-db.build_record()   목적태그·금액·자격·제외·서류 분류
    → build-policyfit-db.convert()          category/goals/stages/tags/eligible 변환
    → codex_boost()                          목적문 LLM 보강
사용:
  python scripts/test-api-full.py            # 분류만 (LLM 없이)
  python scripts/test-api-full.py --codex     # 목적문까지 Codex 보강
"""
import json, sys, argparse, importlib.util
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

kb = _load("kb", "build-knowledge-db.py")        # 분류 (목적태그/금액/자격)
pf = _load("pf", "build-policyfit-db.py")         # 정책핏 변환
scorer = _load("scorer", "score-purposes.py")
codexgen = _load("codexgen", "generate-via-codex-cli.py")


def api_to_knowledge(rec):
    """API 공고 → knowledge-db 레코드 (build_record 재사용).

    API summary를 detail_md로 주면 extract_purposes/amount/exclusions/...
    가 그 텍스트에서 분류를 추출한다.
    """
    notice = {
        "id": rec["id"],
        "title": rec["title"],
        "fields": {
            # 지원대상/지원내용을 fields로 넘기면 분류가 더 정확
            "지원대상": {"value": rec.get("target", "")},
            "지원내용": {"value": rec.get("summary", "")},
        },
    }
    return kb.build_record(notice, rec.get("summary", ""), "")


def codex_boost(rec):
    prompt = codexgen.PROMPT_TEMPLATE.format(
        title=rec.get("title", ""), org=rec.get("category", ""),
        category=rec.get("category", ""), overview=rec.get("summary", "")[:800])
    return codexgen.call_codex(prompt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex", action="store_true", help="목적문 Codex 보강")
    args = ap.parse_args()

    items = json.loads((ROOT / "outputs" / "_api_test.json").read_text(encoding="utf-8"))
    print("=" * 66)
    print(f"API 신규 공고 {len(items)}건 — 전체 분류 체인 적용 테스트")
    print("=" * 66)

    for i, rec in enumerate(items[:4], 1):  # 대표 4건
        krec = api_to_knowledge(rec)        # 1) 분류
        prec = pf.convert(krec)             # 2) 정책핏 변환

        print(f"\n[{i}] {rec['title'][:48]}")
        print(f"  ── 유형 분류 ──")
        print(f"     category : {prec['category']}")
        print(f"     goals    : {prec['goals']}")
        print(f"     stages   : {prec['stages']}")
        print(f"     tags     : {prec['tags']}")
        print(f"     regions  : {prec['regions']}")
        print(f"  ── 지원 규모 ──")
        print(f"     amount   : {prec['amountLabel']}")
        print(f"  ── 자격·요건 ──")
        print(f"     eligible : {prec['eligible']}  (target: {prec['targetShort']})")
        print(f"     prepare  : {len(prec['prepare'])}종 / steps: {len(prec['steps'])}단계")
        print(f"     목적태그 : {krec['support']['purposes']}")
        print(f"  ── 목적문 ──")
        purpose = prec["purpose"]
        sc = scorer.score_purpose(purpose)[0]
        print(f"     룰 {sc}점: {purpose}")
        if args.codex and sc < 70:
            b = codex_boost(rec)
            if b:
                print(f"     LLM {scorer.score_purpose(b)[0]}점: {b}")

    print(f"\n{'='*66}")
    print("→ 유형분류·자격요건은 build-knowledge-db 룰로, 목적문은 LLM으로 처리")
    print("  (API summary 기반이라 금액/서류는 detail.md 전체 체인보다 정밀도 낮음)")


if __name__ == "__main__":
    main()
