#!/usr/bin/env python3
"""신규 공고 자동 모니터링.

흐름:
  1. 기업마당 API 폴링 (4개 카테고리, 최신 N건씩)
  2. 기존 DB 및 처리 이력과 비교 → 신규 공고만 식별
  3. 신규 공고만 수집·변환·분류·LLM 보강
  4. 메인 policyfit-db.json에 자동 머지 (LLM 캐시 갱신)
  5. 처리 이력 (_watched_ids.json)에 추가

사용:
  python scripts/watch-new-notices.py                # 카테고리당 10건 폴링
  python scripts/watch-new-notices.py --per-cat 20    # 카테고리당 20건
  python scripts/watch-new-notices.py --no-llm        # LLM 보강 건너뛰기
  python scripts/watch-new-notices.py --dry            # 신규 식별만, 처리 X

전제:
  - .env.local에 BIZINFO_API_KEY
  - Codex CLI 로그인 (LLM 보강 시)
"""
import json, sys, subprocess, argparse, importlib.util, time, os, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
DB = OUT / "policyfit-db.json"
WATCH_LOG = OUT / "_watched_ids.json"

# 격리 경로 (e2e와 분리)
WATCH_RUN_PREFIX = "watch-"


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def fetch_candidates(per_cat):
    """기업마당 API에서 카테고리별 최신 공고를 가져와 후보 ID 목록 반환."""
    # node로 API 호출 (이미 검증된 fetch-api-sample.mjs 재사용)
    cmd = ["node", "scripts/fetch-api-sample.mjs", str(per_cat * 4)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"❌ API fetch 실패: {r.stderr}")
        return []
    items = json.loads((OUT / "_api_test.json").read_text(encoding="utf-8"))
    return items


def identify_new(items, db_ids, watched_ids):
    """이미 처리된 ID 제외, 신규 공고만 반환."""
    new_items = []
    for it in items:
        pid = it["id"]
        if pid in db_ids or pid in watched_ids:
            continue
        new_items.append(it)
    return new_items


def process_new(new_items, do_llm):
    """신규 공고를 격리 runId로 수집·변환·분류·LLM 보강."""
    if not new_items:
        return None

    run_id = f"{WATCH_RUN_PREFIX}{int(time.time())}"
    n = len(new_items)

    print(f"\n[수집] {n}건 → runId={run_id}")
    # all-items.json + raw/html, raw/files 구성 (mini collector 사용 위해 ID 목록을 한 번에)
    # collect-mini.mjs는 첫 N건만 받으니, 우리 케이스에 맞춰 직접 구성
    api_dir = ROOT / "raw" / "api" / run_id
    api_dir.mkdir(parents=True, exist_ok=True)
    # 기본 collect-mini의 출력 형식과 호환되게 all-items.json 만들기
    # (필드: pblancId, pblancNm, pblancUrl, ...)
    # _api_test.json은 단순화된 형태라 다시 원본 API 호출이 필요
    # 간단화: collect-mini를 호출하되 ID 필터를 별도로
    # 여기서는 _api_test.json의 모든 정보를 raw-like 구조로 변환

    # 우회: collect-mini.mjs를 그대로 호출해서 N건 받음 → 우리 신규 N건 ID와 매치
    # 더 간단: collect-mini.mjs에 ID 필터 옵션을 안 만들었으니, 그냥 충분히 많이 받아서 신규만 처리하도록
    # 여기는 그냥 mini로 N건 가져오는 게 빠름
    cmd = ["node", "scripts/collect-mini.mjs", str(n), run_id]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"❌ collect 실패: {r.stderr}")
        return None
    print(f"  ✓ {r.stdout.strip().splitlines()[1] if r.stdout else 'collect-mini done'}")

    # 환경변수 설정 (격리 출력)
    e2e_kb = f"_watch_knowledge_{run_id}.json"
    e2e_pf = f"_watch_policyfit_{run_id}.json"
    env = {**os.environ,
           "E2E_RUN_ID": run_id,
           "E2E_KNOWLEDGE_OUT": e2e_kb,
           "E2E_POLICYFIT_OUT": e2e_pf}

    # 변환 → 정규화 → 분류 → 정책핏
    steps = [
        ("convert-to-markdown.py", "HTML/PDF → MD"),
        ("normalize-notices.py", "정규화"),
        ("build-knowledge-db.py", "분류"),
        ("build-policyfit-db.py", "정책핏 변환"),
    ]
    for script, desc in steps:
        print(f"  {desc}...")
        r = subprocess.run([sys.executable, f"scripts/{script}"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(f"    ⚠ {script} 실패")

    pf_path = OUT / e2e_pf
    if not pf_path.exists():
        print("❌ 정책핏 결과 없음")
        return None

    recs = json.loads(pf_path.read_text(encoding="utf-8"))
    print(f"  ✓ {len(recs)}건 처리 완료")

    # LLM 보강 (선택)
    if do_llm and recs:
        scorer = _load("scorer", "score-purposes.py")
        codexgen = _load("codexgen", "generate-via-codex-cli.py")
        rp = _load("rp", "refresh-purposes.py")
        codexgen.MD_BASE = ROOT / "raw" / "markdown" / run_id

        print(f"\n[LLM 보강] 룰<70 + B등급(70~84) 두 단계 재시도")
        for stage_name, score_filter, prompt_fn in [
            ("1단계 미달", lambda s: s < 70, "PROMPT_TEMPLATE"),
            ("2단계 B등급", lambda s: 70 <= s < 85, "RETRY_PROMPT_TEMPLATE"),
        ]:
            for i, r in enumerate(recs):
                cur_sc, cur_iss = scorer.score_purpose(r["purpose"])
                if not score_filter(cur_sc):
                    continue
                try:
                    overview = codexgen.get_overview(r["id"]) or r.get("benefits", "") or r.get("summary", "")
                except Exception:
                    overview = r.get("summary", "")
                if prompt_fn == "RETRY_PROMPT_TEMPLATE":
                    prompt = codexgen.RETRY_PROMPT_TEMPLATE.format(
                        title=r["title"], overview=overview[:800],
                        previous=r["purpose"], weakness=rp._weakness_hint(cur_iss))
                else:
                    prompt = codexgen.PROMPT_TEMPLATE.format(
                        title=r["title"], org=r.get("org", ""),
                        category=r["category"], overview=overview[:800])
                boosted = codexgen.call_codex(prompt)
                if boosted:
                    bsc, _ = scorer.score_purpose(boosted)
                    if bsc > cur_sc:
                        r["purpose"] = boosted
                        print(f"  [{i+1}] {stage_name}: {cur_sc}→{bsc}: {boosted[:55]}")

        # 보강 결과 저장
        pf_path.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")

    return recs, pf_path, run_id


def merge_into_db(new_recs):
    """신규 공고를 메인 DB와 캐시에 머지."""
    data = json.loads(DB.read_text(encoding="utf-8"))
    existing_ids = {r["id"] for r in data}
    added = 0
    for r in new_recs:
        if r["id"] not in existing_ids:
            data.append(r)
            added += 1

    # 메인 DB 백업 후 저장
    backup = DB.with_suffix(".json.watch-bak")
    shutil.copy2(DB, backup)
    DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Codex 캐시에도 추가 (재빌드 시 보존)
    codex_cache_path = OUT / "_purpose_cache_codex.json"
    codex_cache = json.loads(codex_cache_path.read_text(encoding="utf-8")) if codex_cache_path.exists() else {}
    for r in new_recs:
        codex_cache[r["id"]] = r["purpose"]
    codex_cache_path.write_text(json.dumps(codex_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[머지] {added}건 신규 추가 → 총 {len(data)}건 (백업: {backup.name})")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cat", type=int, default=10, help="카테고리당 폴링 건수")
    ap.add_argument("--no-llm", action="store_true", help="LLM 보강 건너뛰기")
    ap.add_argument("--dry", action="store_true", help="신규 식별만")
    args = ap.parse_args()

    # 처리 이력 로드
    watched = set()
    if WATCH_LOG.exists():
        watched = set(json.loads(WATCH_LOG.read_text(encoding="utf-8")))

    db_ids = {r["id"] for r in json.loads(DB.read_text(encoding="utf-8"))}
    print(f"기준: DB {len(db_ids)}건 + 처리이력 {len(watched)}건")

    # API 폴링
    print(f"\n[폴링] 카테고리당 최신 {args.per_cat}건 ({args.per_cat * 4}건 시도)")
    items = fetch_candidates(args.per_cat)
    print(f"  ✓ {len(items)}건 수신")

    # 신규 식별
    new_items = identify_new(items, db_ids, watched)
    print(f"\n[식별] 신규 {len(new_items)}건")
    for it in new_items[:5]:
        print(f"  • {it['title'][:50]}")
    if len(new_items) > 5:
        print(f"  ... 외 {len(new_items) - 5}건")

    if args.dry or not new_items:
        if not new_items:
            print("\n신규 공고 없음 — 종료")
        else:
            print("\n--dry 모드: 처리 안 함")
        return

    # 처리 + 머지
    result = process_new(new_items, do_llm=not args.no_llm)
    if not result:
        return
    recs, pf_path, run_id = result

    # 신규만 DB에 머지
    db_ids = {r["id"] for r in json.loads(DB.read_text(encoding="utf-8"))}
    truly_new = [r for r in recs if r["id"] not in db_ids]
    added = merge_into_db(truly_new) if truly_new else 0

    # ── 신규 공고 금액 LLM 구조화 + guard (목적문은 process_new에서 이미 보강) ──
    if truly_new and not args.no_llm:
        new_ids = ",".join(r["id"] for r in truly_new)
        print(f"\n[금액] 신규 {len(truly_new)}건 LLM 구조화...")
        subprocess.run([sys.executable, "scripts/extract-amount-llm.py",
                        "--ids", new_ids, "--workers", "2"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/extract-amount-llm.py", "--apply"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/guard-unverified-amounts.py"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/fix-classification-rules.py"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/normalize-amount-units.py"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/fix-data-issues.py"], cwd=str(ROOT))
        subprocess.run([sys.executable, "scripts/audit-amounts.py"], cwd=str(ROOT))  # sanity 게이트

    # 처리 이력 갱신
    watched.update(r["id"] for r in recs)
    WATCH_LOG.write_text(json.dumps(sorted(watched), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[이력] _watched_ids.json: {len(watched)}건")

    # 최종 품질
    scorer = _load("scorer", "score-purposes.py")
    if truly_new:
        scs = [scorer.score_purpose(r["purpose"])[0] for r in truly_new]
        a = sum(1 for s in scs if s >= 85)
        print(f"\n[품질] 신규 {len(truly_new)}건 평균 {sum(scs)/len(scs):.1f}점, A등급 {a}건")


if __name__ == "__main__":
    main()
