#!/usr/bin/env python3
"""목적문 자동 처리 오케스트레이터.

새 공고가 들어왔을 때 목적문을 자동으로 생성·검증·반영하는 전체 파이프라인.

흐름:
  1. [build]    build-policyfit-db.py 실행
                → knowledge-db.json에서 policyfit-db.json 생성
                → 원본 공고문(detail.md)에서 사업목적 직접 추출 + tossify (룰 베이스)
  2. [score]    score-purposes.py의 채점기로 품질 미달(< threshold) 건 식별
  3. [generate] 미달 건만 LLM(Codex CLI 또는 Gemini)으로 재생성 (캐시 증분)
  4. [verify]   재채점 → 여전히 미달이면 재시도 (최대 max_retries)
  5. [merge]    Codex/Claude 캐시를 머지하여 policyfit-db.json에 반영
  6. [report]   최종 품질 리포트 출력

사용법:
  python scripts/refresh-purposes.py                      # 룰 베이스만 (LLM 없이)
  python scripts/refresh-purposes.py --engine codex       # Codex CLI로 미달분 보강
  python scripts/refresh-purposes.py --engine gemini       # Gemini API로 미달분 보강
  python scripts/refresh-purposes.py --engine codex --threshold 70 --max-retries 2

전제:
  - knowledge-db.json 이 최신 상태 (collect → normalize → build-knowledge-db 선행)
  - Codex 사용 시: codex CLI 로그인 / Gemini 사용 시: .env.local 에 GEMINI_API_KEY
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# 같은 폴더의 score-purposes.py에서 채점기 재사용
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DB = ROOT / "outputs" / "policyfit-db.json"

# 채점기 로드 (파일명에 하이픈이 있어 importlib 사용)
_spec = importlib.util.spec_from_file_location("scorer", SCRIPTS / "score-purposes.py")
_scorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scorer)
score_purpose = _scorer.score_purpose


def run(cmd, desc):
    """서브프로세스 실행 (출력은 그대로 흘려보냄)."""
    print(f"\n{'─'*60}\n▶ {desc}\n{'─'*60}")
    result = subprocess.run([sys.executable] + cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"⚠ {desc} 실패 (exit {result.returncode})")
    return result.returncode == 0


def quality_report(threshold):
    """현재 policyfit-db.json 품질 통계."""
    data = json.loads(DB.read_text(encoding="utf-8"))
    scores = [score_purpose(r["purpose"])[0] for r in data]
    n = len(scores)
    avg = sum(scores) / n
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    for s in scores:
        grades[_scorer.grade(s)[0]] += 1
    below = sum(1 for s in scores if s < threshold)
    return {"n": n, "avg": avg, "grades": grades, "below": below}


def print_report(label, rep, threshold):
    g = rep["grades"]
    print(f"\n[{label}] {rep['n']}건 · 평균 {rep['avg']:.1f}점 "
          f"· A{g['A']} B{g['B']} C{g['C']} D{g['D']} "
          f"· {threshold}점 미만 {rep['below']}건")


def _weakness_hint(issues):
    """채점기 이슈를 LLM이 알아듣기 쉬운 한 줄 약점 설명으로 변환."""
    iss_str = " ".join(issues) if isinstance(issues, list) else str(issues)
    hints = []
    if "배경/동기" in iss_str:
        hints.append("'어려운/막막한/부담스러운' 같은 공감 표현이 부족")
    if "대상자" in iss_str:
        hints.append("대상자(소상공인/창업자 등)가 불명확")
    if "도움/성장" in iss_str:
        hints.append("'돕는/키우는/이어가는' 같은 도움 표현이 부족")
    if "관공서" in iss_str or "합니다/입니다" in iss_str:
        hints.append("관공서 문체가 남아있음 — 해요체로")
    if "단어반복" in iss_str or "중언부언" in iss_str:
        hints.append("같은 단어가 반복됨")
    if "위해/위한" in iss_str or "비문" in iss_str:
        hints.append("문장 구조가 어색함")
    if "길이" in iss_str:
        hints.append("길이가 부적절(50~100자 권장)")
    return "; ".join(hints) if hints else "토스 스타일 규칙 미충족"


def retry_with_codex(threshold, max_retries):
    """Codex로 미달 건만 강화 프롬프트로 재시도. inline 처리."""
    import importlib.util
    db_path = ROOT / "outputs" / "policyfit-db.json"
    codex_cache = ROOT / "outputs" / "_purpose_cache_codex.json"

    spec = importlib.util.spec_from_file_location("codexgen",
                                                  ROOT / "scripts" / "generate-via-codex-cli.py")
    codexgen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(codexgen)

    data = json.loads(db_path.read_text(encoding="utf-8"))
    cache = json.loads(codex_cache.read_text(encoding="utf-8")) if codex_cache.exists() else {}

    for attempt in range(1, max_retries + 1):
        # 미달 건 식별
        targets = []
        for r in data:
            sc, iss = score_purpose(r["purpose"])
            if sc < threshold:
                targets.append((r, sc, iss))

        if not targets:
            print(f"\n✓ 모든 건 {threshold}점 이상")
            break

        print(f"\n[시도 {attempt}/{max_retries}] {len(targets)}건 미달 → 강화 프롬프트로 재생성")

        improved = 0
        for i, (r, sc, iss) in enumerate(targets, 1):
            # 강화 프롬프트 — 이전 결과 + 약점 명시
            weakness = _weakness_hint(iss)
            try:
                overview = codexgen.get_overview(r["id"])
            except Exception:
                overview = ""
            if not overview:
                overview = r.get("summary", "")[:800]

            prompt = codexgen.RETRY_PROMPT_TEMPLATE.format(
                title=r["title"], overview=overview[:800],
                previous=r["purpose"], weakness=weakness,
            )
            new_purpose = codexgen.call_codex(prompt)
            if new_purpose:
                new_sc, _ = score_purpose(new_purpose)
                if new_sc > sc:
                    r["purpose"] = new_purpose
                    cache[r["id"]] = new_purpose
                    improved += 1
                    if i <= 5:  # 처음 5건만 출력
                        print(f"  [{i}/{len(targets)}] {sc}→{new_sc}점: {new_purpose[:55]}")

        # 저장
        db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        codex_cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {improved}/{len(targets)}건 점수 상승, 캐시 저장 완료")

        if improved == 0:
            print("  ※ 이번 시도에서 개선된 건이 없어 중단")
            break


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["codex", "gemini", "none"], default="none",
                    help="미달 건 LLM 보강 엔진 (기본: none = 룰 베이스만)")
    ap.add_argument("--threshold", type=int, default=70,
                    help="품질 합격선 (기본 70 = B등급)")
    ap.add_argument("--max-retries", type=int, default=2,
                    help="미달 건 재생성 최대 횟수 (기본 2)")
    ap.add_argument("--build-only", action="store_true",
                    help="1단계 build만 실행하고 종료")
    args = ap.parse_args()

    print("=" * 60)
    print("정책핏 목적문 자동 처리 파이프라인")
    print(f"engine={args.engine} threshold={args.threshold} max_retries={args.max_retries}")
    print("=" * 60)

    # ── 1. build (룰 베이스) ──
    if not run(["scripts/build-policyfit-db.py"],
               "1/5 build: 원문 목적 추출 + tossify (룰 베이스)"):
        sys.exit(1)

    rep0 = quality_report(args.threshold)
    print_report("build 직후", rep0, args.threshold)

    if args.build_only or args.engine == "none":
        # 룰 베이스만으로도 캐시가 있으면 merge로 기존 LLM 결과 반영
        if (ROOT / "outputs" / "_claude_batch.json").exists() or \
           (ROOT / "outputs" / "_purpose_cache_codex.json").exists():
            run(["scripts/merge-purposes.py"], "merge: 기존 LLM 캐시 반영")
        rep = quality_report(args.threshold)
        print_report("최종", rep, args.threshold)
        print("\n✓ 완료 (LLM 보강 없음)")
        return

    # ── 2~4. LLM 생성 + 검증 루프 ──
    if args.engine == "codex":
        # Codex는 inline 강화 재시도 (점수 미달 건만 RETRY_PROMPT_TEMPLATE 적용)
        retry_with_codex(args.threshold, args.max_retries)
    else:
        # Gemini는 단순 반복 호출 (기존 동작)
        gen_script = "scripts/generate-purposes.py"
        for attempt in range(1, args.max_retries + 1):
            rep = quality_report(args.threshold)
            if rep["below"] == 0:
                break
            print(f"\n[시도 {attempt}/{args.max_retries}] {rep['below']}건 미달")
            run([gen_script], f"generate (gemini, 시도 {attempt})")
            run(["scripts/merge-purposes.py"], "merge")

    # ── 5. 최종 merge ──
    run(["scripts/merge-purposes.py"], "5/5 merge: 최종 반영")

    # ── 6. 리포트 ──
    rep = quality_report(args.threshold)
    print_report("최종", rep, args.threshold)
    if rep["below"] > 0:
        print(f"\n⚠ {rep['below']}건이 여전히 {args.threshold}점 미만 — "
              f"editor.html 로 수동 보정 권장")
    else:
        print("\n✓ 전체 합격선 통과")


if __name__ == "__main__":
    main()
