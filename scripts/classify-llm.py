#!/usr/bin/env python3
"""LLM 분류 재검증 — goals / category / industries.

규칙 분류의 한계(전업종 태그 40%, 비사업 오분류)를 LLM 문맥 판단으로 정밀화.
목적문·제목·대상·지원내용을 보고 정확히 분류.

핵심: '전 업종 대상'인지 '특정 업종 대상'인지 판단 →
  전업종이면 industries=["all"] (변별 중립), 특정이면 해당 업종만.

캐시: outputs/_classify_cache.json
사용:
  python scripts/classify-llm.py --test 3
  python scripts/classify-llm.py --workers 3
  python scripts/classify-llm.py --apply
"""
import json, sys, re, os, subprocess, argparse, shutil, uuid, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
CACHE = ROOT / "outputs" / "_classify_cache.json"

GOALS = ["fund", "sales", "digital", "startup", "hr"]
CATEGORIES = ["운영자금", "고용·인건비", "판로·마케팅", "디지털 전환", "창업 지원",
              "수출·해외진출", "재기·재도전", "시설·환경", "교육·컨설팅", "안전망·세제"]
INDUSTRIES = ["food", "retail", "online", "maker", "service", "etc"]

PROMPT = """다음 정책 사업을 분류하세요. JSON만 출력.

[제목] {title}
[목적] {purpose}
[대상] {target}
[지원내용] {benefits}

분류 기준:
1. goals (해당하는 것 모두, 1~3개):
   - fund: 자금·융자·대출·보증·이차보전·보험료·세제 (사업 운영/시설 자금)
   - sales: 판로·마케팅·홍보·수출·전시·박람회
   - digital: 디지털전환·스마트·온라인화·키오스크·AI
   - startup: 창업·예비창업·사업화·재창업
   - hr: 고용·채용·인력·인건비·일자리·직업훈련
   - ⚠ 주거/출산/양육 등 개인복지성은 어디에도 넣지 말 것(빈 배열)
2. category (정확히 1개): {cats}
3. industries (업종): 특정 업종 대상이면 해당만, 전 업종(업종 무관) 대상이면 ["all"]
   - food(음식), retail(도소매), online(온라인), maker(제조), service(서비스), etc(기타)
   - 대부분의 자금/창업 지원은 업종 무관 → ["all"]
   - "음식점만", "제조업만" 처럼 명시 제한이 있을 때만 특정 업종

출력(JSON 한 줄):
{{"goals": ["fund"], "category": "운영자금", "industries": ["all"], "reason": "한줄"}}
"""


def call_codex_json(prompt):
    out_file = str(ROOT / "outputs" / f"_codex_cls_{uuid.uuid4().hex}.txt")
    codex_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")
    try:
        if os.path.exists(out_file):
            os.remove(out_file)
        subprocess.run(
            [codex_path, "exec", "--skip-git-repo-check",
             "-c", "model_reasoning_effort=low", "-o", out_file, "-"],
            input=prompt.encode("utf-8"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180, shell=True)
        if not os.path.exists(out_file):
            return None
        txt = open(out_file, encoding="utf-8").read().strip()
        os.remove(out_file)
        return txt
    except Exception:
        return None


def parse_json(txt):
    if not txt: return None
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m: return None
    try:
        return json.loads(m.group(0))
    except Exception:
        s = re.sub(r",\s*}", "}", m.group(0).replace("'", '"'))
        try: return json.loads(s)
        except Exception: return None


def validate(c):
    """LLM 분류 결과 정합성 검사."""
    if not isinstance(c, dict): return None
    goals = [g for g in (c.get("goals") or []) if g in GOALS]
    cat = c.get("category") if c.get("category") in CATEGORIES else None
    inds = c.get("industries") or []
    if "all" in inds:
        inds = INDUSTRIES + ["etc"]  # 전업종 = 모든 태그 (단 의도적 표시)
        inds = sorted(set(i for i in inds if i in INDUSTRIES))
    else:
        inds = sorted(set(i for i in inds if i in INDUSTRIES))
        if not inds:
            inds = sorted(INDUSTRIES)  # 불명 → 전체(기존 동작)
    return {"goals": goals, "category": cat, "tags": inds,
            "industryAll": "all" in (c.get("industries") or []),
            "reason": c.get("reason", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ids")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    if args.apply:
        shutil.copy2(DB, DB.with_suffix(".json.classllm-bak"))
        applied = 0
        for r in data:
            c = cache.get(r["id"])
            if not c: continue
            v = validate(c)
            if not v: continue
            if v["goals"]:
                r["goals"] = v["goals"]
            if v["category"]:
                r["category"] = v["category"]
            if v["tags"]:
                r["tags"] = v["tags"]
            r["industryAll"] = v["industryAll"]
            r["classSource"] = "llm"
            applied += 1
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {applied}건 분류 반영 (classllm-bak 백업)")
        return

    if args.ids:
        idset = set(args.ids.split(","))
        targets = [r for r in data if r["id"] in idset]
    else:
        targets = data
    if args.test:
        targets = targets[:args.test]
    todo = [r for r in targets if args.test or args.ids or r["id"] not in cache]
    print(f"분류 대상 {len(targets)}건 중 신규 {len(todo)}건 (worker={args.workers})\n")

    lock = threading.Lock()
    cnt = {"ok": 0, "fail": 0}
    total = len(todo)

    def proc(r):
        prompt = PROMPT.format(
            title=r.get("title", ""), purpose=r.get("purpose", ""),
            target=r.get("targetDetail", "") or r.get("targetShort", ""),
            benefits=(r.get("benefits") or "")[:300],
            cats=" / ".join(CATEGORIES))
        return r["id"], parse_json(call_codex_json(prompt))

    def handle(r, res):
        rid, parsed = res
        with lock:
            if parsed and validate(parsed):
                cache[rid] = parsed
                cnt["ok"] += 1
                n = cnt["ok"] + cnt["fail"]
                v = validate(parsed)
                print(f"[{n}/{total}] ✓ {r['title'][:34]} | {v['category']} {v['goals']} {'전업종' if v['industryAll'] else v['tags']}")
            else:
                cnt["fail"] += 1
            if cnt["ok"] % 10 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.workers <= 1:
        for r in todo: handle(r, proc(r))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(proc, r): r for r in todo}
            for f in as_completed(futs):
                handle(futs[f], f.result())

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 캐시: 성공 {cnt['ok']} / 실패 {cnt['fail']} ({CACHE.name})")
    print(f"  적용: python scripts/classify-llm.py --apply")


if __name__ == "__main__":
    main()
