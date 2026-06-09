#!/usr/bin/env python3
"""B등급 샘플 20건에 강화 재시도 적용 → 점수 상승 측정.

DB는 절대 건드리지 않음. 결과를 _retry_results.json에 저장.
"""
import json, sys, importlib.util, time
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


def main():
    data = json.loads((ROOT / "outputs" / "policyfit-db.json").read_text(encoding="utf-8"))
    sample_ids = json.loads((ROOT / "outputs" / "_retry_sample_ids.json").read_text(encoding="utf-8"))
    id_map = {r["id"]: r for r in data}

    print(f"=== B등급 샘플 {len(sample_ids)}건 강화 재시도 ===\n")

    results = []
    improved = 0
    total_gain = 0
    start = time.time()

    for i, pid in enumerate(sample_ids, 1):
        r = id_map.get(pid)
        if not r:
            continue

        prev_p = r["purpose"]
        prev_sc, prev_iss = sc.score_purpose(prev_p)
        weakness = rp._weakness_hint(prev_iss)

        try:
            overview = cg.get_overview(pid)
        except Exception:
            overview = ""
        if not overview:
            overview = r.get("benefits") or r.get("targetDetail") or r.get("summary", "")[:800]

        prompt = cg.RETRY_PROMPT_TEMPLATE.format(
            title=r["title"], overview=overview[:800],
            previous=prev_p, weakness=weakness)

        new_p = cg.call_codex(prompt)
        if new_p:
            new_sc, _ = sc.score_purpose(new_p)
            gain = new_sc - prev_sc
            if new_sc > prev_sc:
                improved += 1
                total_gain += gain
            print(f"[{i:2d}] {prev_sc}→{new_sc}점 ({gain:+d}) {r['title'][:32]}")
            print(f"      이전: {prev_p[:75]}")
            print(f"      재시도: {new_p[:75]}")
            results.append({
                "id": pid, "title": r["title"], "weakness": weakness,
                "prev_score": prev_sc, "prev_purpose": prev_p,
                "new_score": new_sc, "new_purpose": new_p, "gain": gain,
            })
        else:
            print(f"[{i:2d}] Codex 실패 — {r['title'][:30]}")
            results.append({"id": pid, "error": "codex_failed", "prev_score": prev_sc})

    elapsed = time.time() - start
    n = len([r for r in results if "new_score" in r])
    avg_gain = total_gain / improved if improved else 0
    print(f"\n=== 결과 ===")
    print(f"처리: {n}/{len(sample_ids)}건, 시간 {elapsed:.0f}초")
    print(f"점수 상승: {improved}건, 평균 +{avg_gain:.1f}점")
    if n:
        prev_avg = sum(r["prev_score"] for r in results if "new_score" in r) / n
        new_avg = sum(r["new_score"] for r in results if "new_score" in r) / n
        a_before = sum(1 for r in results if r.get("prev_score",0) >= 85)
        a_after = sum(1 for r in results if r.get("new_score",0) >= 85)
        print(f"평균 점수: {prev_avg:.1f} → {new_avg:.1f}")
        print(f"A등급(85+): {a_before} → {a_after}건 (+{a_after - a_before})")

    (ROOT / "outputs" / "_retry_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ outputs/_retry_results.json 저장 (DB는 건드리지 않음)")


if __name__ == "__main__":
    main()
