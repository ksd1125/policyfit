#!/usr/bin/env python3
"""rebuild로 누락된 외부(모니터링/e2e) 공고 보존.

build-knowledge-db는 메인 runId(20260601-224706)만 처리하므로,
watch-new-notices나 e2e로 추가됐던 공고가 rebuild 시 사라진다.

이 스크립트는 직전 백업(pre-rebuild)에서 현재 DB에 없는 ID를 찾아 복원한다.
rebuild-all 파이프라인 마지막 단계로 실행.

사용:
  python scripts/preserve-external-notices.py --from outputs/policyfit-db.json.pre-rebuild
"""
import json, sys, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="outputs/policyfit-db.json.pre-rebuild",
                    help="복원 출처 백업")
    args = ap.parse_args()

    src_path = ROOT / args.src
    if not src_path.exists():
        print(f"출처 백업 없음: {src_path} — 건너뜀")
        return

    cur = json.loads(DB.read_text(encoding="utf-8"))
    old = json.loads(src_path.read_text(encoding="utf-8"))
    cur_ids = {r["id"] for r in cur}

    restored = [r for r in old if r["id"] not in cur_ids]
    if not restored:
        print("복원할 외부 공고 없음 (현재 DB가 최신)")
        return

    print(f"복원 대상: {len(restored)}건")
    for r in restored:
        print(f"  + {r['id']} | {r['title'][:50]}")
    cur.extend(restored)
    DB.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {len(restored)}건 복원, 총 {len(cur)}건")


if __name__ == "__main__":
    main()
