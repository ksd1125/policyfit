#!/usr/bin/env python3
"""API로 수신한 새 공고에 목적문 추출 파이프라인을 적용해 테스트.

흐름: _api_test.json (Node 수집) → tossify 룰 → score 검증 → (선택)Codex LLM 보강
사용:
  python scripts/test-api-purposes.py            # 룰 베이스만
  python scripts/test-api-purposes.py --codex     # 미달분(70점 미만) Codex 자동 보강
"""
import json, sys, argparse, importlib.util
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# 기존 스크립트의 함수들 재사용
builder = _load("builder", "build-policyfit-db.py")       # 룰 추출/tossify
scorer = _load("scorer", "score-purposes.py")             # 채점기
codexgen = _load("codexgen", "generate-via-codex-cli.py")  # call_codex, PROMPT_TEMPLATE


def codex_boost(rec):
    """미달 공고를 Codex LLM으로 보강. generate-via-codex-cli.py의 call_codex 재사용.

    핵심: detail.md 대신 API summary를 프롬프트에 넣는다.
    """
    prompt = codexgen.PROMPT_TEMPLATE.format(
        title=rec.get("title", ""),
        org=rec.get("category", ""),
        category=rec.get("category", ""),
        overview=rec.get("summary", "")[:800],   # API 사업개요
    )
    return codexgen.call_codex(prompt)   # ← LLM 보강의 핵심 함수


def make_purpose(rec):
    """API summary → 목적문 (build-policyfit-db.py 로직과 동일).

    원문 detail.md가 없는 새 공고이므로, API summary를
    _extract_purpose_core(원문 파싱) → tossify(토스 변환) 으로 처리.
    """
    summary = rec.get("summary", "")
    # 1) 원문 파싱 (☞ 이전 = 목적, 법령/공고 꼬리 제거)
    raw = builder._extract_purpose_core(summary)
    if not raw:
        return None
    # 2) 토스 스타일 변환
    return builder.tossify(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex", action="store_true",
                    help="70점 미만 공고를 Codex LLM으로 자동 보강")
    ap.add_argument("--threshold", type=int, default=70)
    args = ap.parse_args()

    api_file = ROOT / "outputs" / "_api_test.json"
    if not api_file.exists():
        print("❌ outputs/_api_test.json 없음. 먼저 실행: node scripts/fetch-api-sample.mjs")
        sys.exit(1)

    items = json.loads(api_file.read_text(encoding="utf-8"))
    print("=" * 64)
    print(f"API 신규 공고 {len(items)}건 — 목적문 자동 추출"
          + (" + Codex 보강" if args.codex else "") + " 테스트")
    print("=" * 64)

    rule_scores, final_scores, boosted = [], [], 0
    for i, rec in enumerate(items, 1):
        purpose = make_purpose(rec)
        if not purpose:
            print(f"\n[{i}] {rec['title'][:50]}\n    ⚠ 추출 실패")
            continue
        sc, iss = scorer.score_purpose(purpose)
        rule_scores.append(sc)

        print(f"\n[{i}] {rec['title'][:50]}  ({rec.get('category','')})")
        print(f"    룰  {sc}점 {scorer.grade(sc)}: {purpose}")

        # ── 미달분 Codex 자동 보강 ──
        if args.codex and sc < args.threshold:
            boosted_purpose = codex_boost(rec)
            if boosted_purpose:
                bsc, _ = scorer.score_purpose(boosted_purpose)
                print(f"    LLM {bsc}점 {scorer.grade(bsc)}: {boosted_purpose}")
                final_scores.append(max(sc, bsc))
                if bsc > sc:
                    boosted += 1
                continue
            else:
                print(f"    LLM 보강 실패 → 룰 결과 유지")
        final_scores.append(sc)

    if rule_scores:
        print(f"\n{'='*64}")
        ra = sum(rule_scores) / len(rule_scores)
        print(f"룰 베이스:  평균 {ra:.1f}점, "
              f"70점+ {sum(1 for s in rule_scores if s>=70)}/{len(rule_scores)}건")
        if args.codex:
            fa = sum(final_scores) / len(final_scores)
            print(f"Codex 보강: 평균 {fa:.1f}점, "
                  f"70점+ {sum(1 for s in final_scores if s>=70)}/{len(final_scores)}건 "
                  f"({boosted}건 상승)")
        else:
            print(f"→ --codex 옵션으로 미달분 LLM 자동 보강 가능")


if __name__ == "__main__":
    main()
