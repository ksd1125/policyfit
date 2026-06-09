#!/usr/bin/env python3
"""End-to-end 테스트: 새 공고를 전체 파이프라인에 통과시켜 검증.

격리 방식:
  - 별도 runId (e2e-*) + 환경변수로 출력 경로 분리
  - 기존 knowledge-db.json / policyfit-db.json 은 백업 후 복구

흐름:
  1. 백업 → 2. 수집(HTML+첨부 PDF) → 3. HTML/PDF → MD
  → 4. 정규화 → 5. 분류 → 6. 정책핏 변환 → 7. (옵션)LLM 보강 → 8. 복구

사용:
  python scripts/run-e2e.py [건수]              # 룰만
  python scripts/run-e2e.py [건수] --codex      # LLM 보강 포함
"""
import os, sys, json, shutil, subprocess, importlib.util, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

_ap = argparse.ArgumentParser()
_ap.add_argument("n", nargs="?", default="5", help="수집 건수")
_ap.add_argument("--codex", action="store_true", help="목적문 LLM 보강")
ARGS = _ap.parse_args()
N = ARGS.n


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sh(cmd, env=None, desc=""):
    print(f"\n{'─'*58}\n▶ {desc}\n{'─'*58}")
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=str(ROOT), env=e)
    if r.returncode != 0:
        print(f"⚠ 실패 (exit {r.returncode})")
        return False
    return True


def main():
    # ── 0. 백업 ──
    backups = {}
    for f in ["knowledge-db.json", "policyfit-db.json"]:
        src = OUT / f
        if src.exists():
            bak = OUT / (f + ".e2e-bak")
            shutil.copy2(src, bak)
            backups[src] = bak
    print(f"백업: {[b.name for b in backups.values()]}")

    # 격리 출력 경로
    E2E_KB = "_e2e_knowledge.json"
    E2E_PF = "_e2e_policyfit.json"

    try:
        # ── 1. 미니 수집 (runId는 collect-mini가 생성, stdout에서 파싱) ──
        print(f"\n{'='*58}\nEND-TO-END 테스트 ({N}건)\n{'='*58}")
        r = subprocess.run(["node", "scripts/collect-mini.mjs", str(N)],
                           cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        print(r.stdout)
        run_id = None
        for line in r.stdout.splitlines():
            if line.startswith("runId="):
                run_id = line.split("=", 1)[1].strip()
        if not run_id:
            print("❌ runId 파싱 실패"); return
        env = {"E2E_RUN_ID": run_id,
               "E2E_KNOWLEDGE_OUT": E2E_KB,
               "E2E_POLICYFIT_OUT": E2E_PF}

        # ── 2~5. 변환·정규화·분류 (격리 runId) ──
        sh([sys.executable, "scripts/convert-to-markdown.py"], env,
           "convert-to-markdown: 상세 HTML → detail.md")
        sh([sys.executable, "scripts/normalize-notices.py"], env,
           "normalize-notices: 8필드 정규화")
        sh([sys.executable, "scripts/build-knowledge-db.py"], env,
           "build-knowledge-db: 목적태그·금액·자격·서류 분류 (상세 HTML 기반)")
        sh([sys.executable, "scripts/build-policyfit-db.py"], env,
           "build-policyfit-db: 정책핏 변환")

        # ── 6. 첨부 통계 ──
        files_dir = ROOT / "raw" / "files" / run_id
        att_count = 0
        if files_dir.exists():
            for d in files_dir.iterdir():
                if d.is_dir():
                    att_count += sum(1 for _ in d.iterdir())
        md_dir = ROOT / "raw" / "markdown" / run_id
        md_count = 0
        if md_dir.exists():
            for d in md_dir.iterdir():
                if d.is_dir():
                    md_count += sum(1 for f in d.iterdir() if f.suffix == ".md")

        # ── 7. 결과 확인 ──
        e2e_pf = OUT / E2E_PF
        if not e2e_pf.exists():
            print("❌ 결과 없음"); return
        recs = json.loads(e2e_pf.read_text(encoding="utf-8"))
        print(f"\n{'='*58}\nEND-TO-END 결과: {len(recs)}건\n{'='*58}")

        scorer = _load("scorer", "score-purposes.py")
        rule_scores = [scorer.score_purpose(r["purpose"])[0] for r in recs]
        amt_ok = sum(1 for r in recs if r["amountLabel"] != "지원 규모 확인 필요")
        prep_ok = sum(1 for r in recs if len(r["prepare"]) > 2)

        for r, sc in zip(recs, rule_scores):
            print(f"\n[{r['title'][:46]}]")
            print(f"  분류: {r['category']} | goals={r['goals']} | tags={r['tags']}")
            print(f"  규모: {r['amountLabel']}")
            print(f"  자격: {r['eligible']} | 준비물 {len(r['prepare'])}종 | 절차 {len(r['steps'])}단계")
            print(f"  목적(룰 {sc}점): {r['purpose'][:65]}")

        # ── 8. LLM 보강: 2단계 (첫 시도 + 약점 피드백 강화 재시도) ──
        boosted_scores = list(rule_scores)
        if ARGS.codex:
            codexgen = _load("codexgen", "generate-via-codex-cli.py")
            rp = _load("rp", "refresh-purposes.py")
            codexgen.MD_BASE = ROOT / "raw" / "markdown" / run_id

            def _get_overview(rec):
                try:
                    ov = codexgen.get_overview(rec["id"])
                    if ov: return ov
                except Exception:
                    pass
                return rec.get("benefits") or rec.get("summary", "")[:800]

            # 1단계: 룰 70점 미만 — 첫 시도 (PROMPT_TEMPLATE)
            print(f"\n{'─'*58}\n▶ LLM 1단계: 룰 70점 미만 첫 시도\n{'─'*58}")
            for i, (r, sc) in enumerate(zip(recs, rule_scores)):
                if sc >= 70:
                    continue
                prompt = codexgen.PROMPT_TEMPLATE.format(
                    title=r["title"], org=r.get("org", ""),
                    category=r["category"], overview=_get_overview(r)[:800])
                boosted = codexgen.call_codex(prompt)
                if boosted:
                    bsc, _ = scorer.score_purpose(boosted)
                    if bsc > sc:
                        r["purpose"] = boosted
                        boosted_scores[i] = bsc
                    print(f"  [{i+1}] {sc}→{bsc}: {boosted[:55]}")

            # 2단계: 70~84점 (B등급) — 강화 프롬프트로 A 승급 시도
            print(f"\n{'─'*58}\n▶ LLM 2단계: B등급(70~84) 강화 재시도\n{'─'*58}")
            for i, r in enumerate(recs):
                cur_sc, cur_iss = scorer.score_purpose(r["purpose"])
                if cur_sc >= 85 or cur_sc < 70:
                    continue
                weakness = rp._weakness_hint(cur_iss)
                prompt = codexgen.RETRY_PROMPT_TEMPLATE.format(
                    title=r["title"], overview=_get_overview(r)[:800],
                    previous=r["purpose"], weakness=weakness)
                boosted = codexgen.call_codex(prompt)
                if boosted:
                    bsc, _ = scorer.score_purpose(boosted)
                    if bsc > cur_sc:
                        r["purpose"] = boosted
                        boosted_scores[i] = max(boosted_scores[i], bsc)
                    print(f"  [{i+1}] {cur_sc}→{bsc}: {boosted[:55]}")

            (OUT / E2E_PF).write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── 정밀도 리포트 ──
        print(f"\n{'─'*58}\n전체 체인 정밀도:")
        print(f"  상세 HTML → MD: {md_count}건")
        print(f"  첨부 파일 다운로드: {att_count}개")
        print(f"  금액 추출 성공: {amt_ok}/{len(recs)}건 ({amt_ok*100//max(len(recs),1)}%)")
        print(f"  준비물 3종+: {prep_ok}/{len(recs)}건")
        if ARGS.codex:
            ra = sum(rule_scores) / len(rule_scores)
            ba = sum(boosted_scores) / len(boosted_scores)
            print(f"  목적문 평균: 룰 {ra:.1f}점 → LLM 보강 {ba:.1f}점")

    finally:
        # ── 7. 복구 ──
        for src, bak in backups.items():
            shutil.move(str(bak), str(src))
        print(f"\n복구 완료: 기존 데이터 원상복구 ({list(b.name for b in backups.keys())})")
        # 격리 임시 출력 정리
        for f in [E2E_KB, E2E_PF]:
            p = OUT / f
            if p.exists():
                print(f"  (격리 결과 보존: outputs/{f})")


if __name__ == "__main__":
    main()
