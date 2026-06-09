#!/usr/bin/env python3
"""목적문의 사실 정확성 검증 (환각·왜곡 검출).

LLM에게 [원문 사업개요 vs 생성된 목적문]을 비교시켜:
  - OK: 사실에 부합
  - DRIFT: 원문에 없는 내용 추가 (경미)
  - HALLUCINATION: 명백한 거짓·다른 사업 묘사

사용:
  python scripts/verify-factuality.py --sample 20    # 무작위 20건
  python scripts/verify-factuality.py --score 100    # 100점 만점 대상만
  python scripts/verify-factuality.py --id PBLN_xxx  # 특정 공고만
"""
import json, sys, importlib.util, argparse, random, re
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


cg = _load("cg", "generate-via-codex-cli.py")


VERIFY_PROMPT = """다음 정책 사업의 [원문 정보]와 [생성된 목적문]을 비교해 사실 정확성을 평가해주세요.

[원문 정보]
제목: {title}
대상: {target}
지원내용: {benefits}
사업개요: {overview}

[생성된 목적문]
{purpose}

평가 기준:
- OK: 목적문의 모든 사실이 원문(제목/대상/지원내용/사업개요 어디에든)에 근거함
- DRIFT: 원문에 없는 사소한 형용사·맥락 추가 (예: "막막한", "어려운" 같은 정서적 표현)
- HALLUCINATION: 원문과 명백히 다른 사업·거짓 정보·잘못된 대상자·잘못된 지역

판단 원칙:
- 지역·대상·지원 분야는 제목에 있어도 OK입니다 (예: "[경북] 경주시 ... 사과")
- 형용사 표현 차이(어려운/막막한/부담스러운 등)는 DRIFT입니다 (절대 HALLUCINATION 아님)
- 사실 자체가 틀린 경우만 HALLUCINATION (예: 경기 사업인데 강원이라고 함)

다음 형식으로 답변:
판정: OK | DRIFT | HALLUCINATION
근거: (한 줄로 설명)
"""


def parse_verdict(text):
    """LLM 응답에서 판정·근거 파싱."""
    if not text:
        return "ERROR", "응답 없음"
    # 판정 찾기
    m = re.search(r'판정\s*[:：]\s*(OK|DRIFT|HALLUCINATION)', text, re.IGNORECASE)
    verdict = m.group(1).upper() if m else "PARSE_ERROR"
    # 근거
    m = re.search(r'근거\s*[:：]\s*(.+?)(?:\n|$)', text)
    reason = m.group(1).strip() if m else text[:80]
    return verdict, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10, help="검증 표본 크기")
    ap.add_argument("--score", type=int, help="특정 점수의 건만 (예: 100)")
    ap.add_argument("--id", help="특정 공고 ID만")
    ap.add_argument("--md-base", default="raw/markdown/20260601-224706",
                    help="원문 디렉토리")
    args = ap.parse_args()

    sc = _load("sc", "score-purposes.py")
    cg.MD_BASE = ROOT / args.md_base

    data = json.loads((ROOT / "outputs" / "policyfit-db.json").read_text(encoding="utf-8"))

    # 대상 선별
    if args.id:
        targets = [r for r in data if r["id"] == args.id]
    elif args.score:
        targets = [r for r in data if sc.score_purpose(r["purpose"])[0] == args.score]
        random.seed(42); random.shuffle(targets)
        targets = targets[:args.sample]
    else:
        random.seed(42)
        targets = random.sample(data, min(args.sample, len(data)))

    print(f"=== 사실 정확성 검증 ({len(targets)}건) ===\n")

    results = {"OK": 0, "DRIFT": 0, "HALLUCINATION": 0, "ERROR": 0, "PARSE_ERROR": 0}
    issues = []

    for i, r in enumerate(targets, 1):
        try:
            overview = cg.get_overview(r["id"])
        except Exception:
            overview = ""
        if not overview:
            overview = r.get("benefits") or r.get("summary", "")[:800]

        prompt = VERIFY_PROMPT.format(
            title=r.get("title", ""),
            target=r.get("targetDetail", "") or r.get("targetShort", ""),
            benefits=r.get("benefits", "")[:400],
            overview=overview[:1200],
            purpose=r["purpose"])
        resp = cg.call_codex(prompt)
        verdict, reason = parse_verdict(resp)
        results[verdict] = results.get(verdict, 0) + 1

        mark = {"OK": "✓", "DRIFT": "△", "HALLUCINATION": "✗"}.get(verdict, "?")
        print(f"[{i:2d}] {mark} {verdict}: {r['title'][:32]}")
        print(f"     목적: {r['purpose'][:70]}")
        if verdict in ("DRIFT", "HALLUCINATION", "ERROR", "PARSE_ERROR"):
            print(f"     근거: {reason[:90]}")
            issues.append({
                "id": r["id"], "title": r["title"], "verdict": verdict,
                "purpose": r["purpose"], "reason": reason,
            })

    print(f"\n=== 결과 ===")
    n = sum(results.values())
    for k in ["OK", "DRIFT", "HALLUCINATION", "ERROR", "PARSE_ERROR"]:
        if results.get(k, 0):
            pct = results[k] * 100 // n
            print(f"  {k}: {results[k]}건 ({pct}%)")

    if issues:
        out = ROOT / "outputs" / "_factuality_issues.json"
        out.write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {len(issues)}건 이슈 outputs/_factuality_issues.json 저장")


if __name__ == "__main__":
    main()
