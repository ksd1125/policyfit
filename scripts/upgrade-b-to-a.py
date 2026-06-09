#!/usr/bin/env python3
"""B등급 전체에 강화 재시도 적용 → 캐시·DB에 반영.

사용법:
  python scripts/upgrade-b-to-a.py            # 전수 (~20분)
  python scripts/upgrade-b-to-a.py --limit 50  # 50건만
  python scripts/upgrade-b-to-a.py --dry       # 점수 비교만, 저장 X
"""
import json, sys, importlib.util, argparse, time, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

sc = _load("sc", "score-purposes.py")
cg = _load("cg", "generate-via-codex-cli.py")
rp = _load("rp", "refresh-purposes.py")

DB = ROOT / "outputs" / "policyfit-db.json"
CACHE_CLAUDE = ROOT / "outputs" / "_claude_batch.json"
CACHE_CODEX = ROOT / "outputs" / "_purpose_cache_codex.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="처리 건수 제한")
    ap.add_argument("--dry", action="store_true", help="저장하지 않음")
    ap.add_argument("--threshold", type=int, default=85, help="목표 등급 (기본 85=A)")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))

    # B등급 (70~threshold-1점) 식별
    targets = []
    for r in data:
        sc_v, iss = sc.score_purpose(r["purpose"])
        if 70 <= sc_v < args.threshold:
            targets.append((r, sc_v, iss))
    targets.sort(key=lambda x: x[1])  # 낮은 점수 우선

    if args.limit:
        targets = targets[:args.limit]

    n = len(targets)
    print(f"B등급(70~{args.threshold-1}) {n}건 처리 시작")
    if args.dry:
        print("DRY-RUN: DB·캐시 저장 안 함\n")

    # 캐시 로드
    claude_cache = json.loads(CACHE_CLAUDE.read_text(encoding="utf-8")) if CACHE_CLAUDE.exists() else {}
    codex_cache = json.loads(CACHE_CODEX.read_text(encoding="utf-8")) if CACHE_CODEX.exists() else {}

    # 백업
    if not args.dry:
        backup = DB.with_suffix(".json.upgrade-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}")

    improved = 0
    failed = 0
    score_changes = []
    start = time.time()
    save_every = 25

    for i, (r, prev_sc, prev_iss) in enumerate(targets, 1):
        pid = r["id"]
        weakness = rp._weakness_hint(prev_iss)

        try:
            overview = cg.get_overview(pid)
        except Exception:
            overview = ""
        if not overview:
            overview = r.get("benefits") or r.get("targetDetail") or r.get("summary", "")[:800]

        prompt = cg.RETRY_PROMPT_TEMPLATE.format(
            title=r["title"], overview=overview[:800],
            previous=r["purpose"], weakness=weakness)

        new_p = cg.call_codex(prompt)
        if not new_p:
            failed += 1
            print(f"  [{i:3d}/{n}] FAIL {prev_sc}점: {r['title'][:32]}")
            continue

        new_sc, _ = sc.score_purpose(new_p)
        if new_sc > prev_sc:
            improved += 1
            score_changes.append((prev_sc, new_sc))
            if not args.dry:
                r["purpose"] = new_p
                # Claude 작성 캐시가 우선이지만 새 결과로 갱신
                if pid in claude_cache:
                    claude_cache[pid] = new_p
                codex_cache[pid] = new_p

        # 진행률
        if i % 5 == 0 or i == n:
            elapsed = time.time() - start
            eta = (elapsed / i) * (n - i)
            print(f"  [{i:3d}/{n}] {prev_sc}→{new_sc}점 ({i*100//n}%) "
                  f"elapsed {elapsed:.0f}초, ETA {eta:.0f}초")

        # 주기적 저장 (중간 중단 대비)
        if not args.dry and improved > 0 and improved % save_every == 0:
            DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            CACHE_CLAUDE.write_text(json.dumps(claude_cache, ensure_ascii=False, indent=2), encoding="utf-8")
            CACHE_CODEX.write_text(json.dumps(codex_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    # 최종 저장
    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        CACHE_CLAUDE.write_text(json.dumps(claude_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        CACHE_CODEX.write_text(json.dumps(codex_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.time() - start
    print(f"\n=== 완료 ({elapsed/60:.1f}분) ===")
    print(f"처리: {n}건, 점수 상승: {improved}건, 실패: {failed}건")
    if score_changes:
        avg_prev = sum(a for a, _ in score_changes) / len(score_changes)
        avg_new = sum(b for _, b in score_changes) / len(score_changes)
        a_gained = sum(1 for _, b in score_changes if b >= 85)
        print(f"평균: {avg_prev:.1f} → {avg_new:.1f}점 (+{avg_new-avg_prev:.1f})")
        print(f"A등급(85+) 신규: {a_gained}건")

    # 전체 DB 검증
    if not args.dry:
        scores = [sc.score_purpose(r["purpose"])[0] for r in data]
        a = sum(1 for s in scores if s >= 85)
        b = sum(1 for s in scores if 70 <= s < 85)
        c = sum(1 for s in scores if s < 70)
        print(f"\n전체 DB ({len(data)}건):")
        print(f"  A: {a} ({a*100//len(data)}%)")
        print(f"  B: {b} ({b*100//len(data)}%)")
        print(f"  C+: {c}")
        print(f"  평균: {sum(scores)/len(scores):.1f}점")


if __name__ == "__main__":
    main()
