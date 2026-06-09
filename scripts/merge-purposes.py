#!/usr/bin/env python3
"""Codex + Claude 목적문을 머지하여 policyfit-db.json에 반영.

각 정책 ID에 대해:
1. Codex 캐시와 Claude 배치 중 score 높은 것 선택
2. 둘 다 없으면 기존 v4 목적 유지

사용법:
  python scripts/merge-purposes.py          # 머지 + 저장
  python scripts/merge-purposes.py --dry     # 미리보기만
"""

import json, sys, os, argparse
from pathlib import Path
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
CODEX = ROOT / "outputs" / "_purpose_cache_codex.json"
CLAUDE = ROOT / "outputs" / "_claude_batch.json"

# 스코어러 로드
spec = importlib.util.spec_from_file_location("sp", ROOT / "scripts" / "score-purposes.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    codex = json.loads(CODEX.read_text(encoding="utf-8")) if CODEX.exists() else {}
    claude = json.loads(CLAUDE.read_text(encoding="utf-8")) if CLAUDE.exists() else {}

    src_count = {"codex": 0, "claude": 0, "keep": 0}
    improved = 0

    for r in data:
        pid = r["id"]
        old = r["purpose"]
        old_score = sp.score_purpose(old)[0]

        candidates = []
        if pid in codex:
            candidates.append(("codex", codex[pid], sp.score_purpose(codex[pid])[0]))
        if pid in claude:
            candidates.append(("claude", claude[pid], sp.score_purpose(claude[pid])[0]))

        if not candidates:
            src_count["keep"] += 1
            continue

        # score 가장 높은 후보 선택
        best_src, best_text, best_score = max(candidates, key=lambda x: x[2])

        # 기존보다 높을 때만 교체
        if best_score > old_score:
            if not args.dry:
                r["purpose"] = best_text
            src_count[best_src] += 1
            improved += 1
        else:
            src_count["keep"] += 1

    # 통계
    scores = [sp.score_purpose(r["purpose"])[0] for r in data]
    avg = sum(scores) / len(scores)
    ga = sum(1 for s in scores if s >= 85)
    gb = sum(1 for s in scores if 70 <= s < 85)

    print(f"머지 결과 ({'미리보기' if args.dry else '적용'}):")
    print(f"  Codex 채택: {src_count['codex']}건")
    print(f"  Claude 채택: {src_count['claude']}건")
    print(f"  기존 유지: {src_count['keep']}건")
    print(f"  개선됨: {improved}건")
    print(f"\n전체 평균: {avg:.1f}점 (A:{ga}, B:{gb}, A+B:{(ga+gb)*100//len(data)}%)")

    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {DB} 저장 완료")


if __name__ == "__main__":
    main()
