#!/usr/bin/env python3
"""전업종(industryAll/전 태그)으로 분류됐지만 특정 도메인 의심 정책을 Gemini로 정밀 재분류.

판단: 이 지원사업이 '모든 업종의 소상공인'에게 열려 있는가(universal),
      아니면 특정 산업·업종 기업만 대상인가(specific + 어떤 업종).
규칙이 아닌 LLM 의미판단 — '우주항공청 가족 창업'(일반) vs '연구실 안전관리'(특정) 구분.

키는 .env.local에서 메모리로만 읽음. gemini-2.5-flash, thinkingBudget:0.
적용: --apply 시 DB의 industryAll/tags 갱신(+ 백업). 미지정 시 dry-run(제안만).
"""
import json, re, sys, time, urllib.request, urllib.error, argparse
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs/policyfit-db.json"
INDG = ["food", "retail", "service", "online", "maker"]
GROUP_KO = {"food": "음식·외식", "retail": "도소매·유통", "service": "서비스업", "online": "온라인·이커머스", "maker": "제조·기술"}
SPECIFIC = ['연구실','수리조선','조선해양','선박','방사선','스마트공장','반도체','이차전지','수소','항공','방산',
            '바이오','의약','신약','화학','금형','뿌리산업','로봇','플랜트','원자력','국방','드론','우주',
            'ESG 경영 컨설','지식재산','IP보증','특허','기술분쟁','M&A','기업승계','벤처투자','스케일업','규제자유특구']

def key():
    for line in (ROOT/".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=",1)[1].strip()
    return None

def is_universal(p):
    return p.get("industryAll") == True or (p.get("industryAll") is None and len(p.get("tags",[])) >= 6)

def call_gemini(prompt, k):
    body = json.dumps({"contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0,"maxOutputTokens":200,"thinkingConfig":{"thinkingBudget":0},
            "responseMimeType":"application/json"}}).encode("utf-8")
    url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={k}"
    for a in range(4):
        try:
            d=json.loads(urllib.request.urlopen(urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"}),timeout=30).read())
            txt="".join(x.get("text","") for x in d["candidates"][0].get("content",{}).get("parts",[]))
            return json.loads(txt)
        except urllib.error.HTTPError as e:
            if e.code in (503,429) and a<3: time.sleep(3); continue
            return {"error":f"HTTP {e.code}"}
        except Exception as e:
            return {"error":str(e)[:80]}

def build_prompt(p):
    return "\n".join([
        "다음 정부 지원사업이 '모든 업종의 일반 소상공인'에게 열려 있는지, 아니면 '특정 산업·업종 기업'만 대상인지 판정하세요.",
        "판정 기준(엄격히):",
        "- universal=true: 업종/산업 제한 없이 일반 소상공인·중소기업 누구나 신청 가능(자금·판로·고용·창업·지식재산·ESG 등 범용 지원). 특정 대상집단[예: 이주직원 가족] 한정이어도 '업종 무관'이면 universal.",
        "- universal=false: 신청자격이 특정 산업·분야 기업으로 제한됨(예: 조선·선박·해양, 연구소, 의약·바이오, 로봇, 반도체, 방사선 등). '중소기업'이라는 표현이 있어도 특정 산업분야로 한정되면 반드시 universal=false.",
        "※ 중요: reason에 특정 산업명(조선/선박/의약/로봇/연구소 등)을 적었다면 universal은 반드시 false여야 한다(모순 금지).",
        "industries 후보(해당하는 것만 배열): food(음식외식) retail(도소매) service(서비스) online(온라인) maker(제조·기술).",
        '반드시 JSON만 출력: {"universal": true|false, "industries": ["maker", ...], "reason": "20자 이내"}',
        "",
        f"제목: {p.get('title')}",
        f"목적: {(p.get('purpose') or '')[:120]}",
        f"대상: {(p.get('targetDetail') or '')[:120]}",
    ])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); args=ap.parse_args()
    k=key()
    db=json.loads(DB.read_text(encoding="utf-8"))
    suspects=[p for p in db if is_universal(p) and any(s in p.get("title","") for s in SPECIFIC)]
    print(f"의심 {len(suspects)}건 재분류 시작 (apply={args.apply})\n")
    changes=[]
    for p in suspects:
        r=call_gemini(build_prompt(p), k)
        if r.get("error"): print(f"  [ERR] {r['error']} :: {p['title'][:30]}"); continue
        uni=r.get("universal"); inds=[g for g in r.get("industries",[]) if g in INDG]
        cur_uni=is_universal(p)
        if uni is False and inds:
            changes.append((p, inds, r.get("reason","")))
            print(f"  [특정] {p['title'][:38]}\n         → {inds} ({r.get('reason','')})")
        else:
            print(f"  [범용유지] {p['title'][:38]} ({r.get('reason','')})")
        time.sleep(4.5)  # 15 RPM 준수
    print(f"\n특정업종으로 교정 대상: {len(changes)}건")
    if args.apply and changes:
        bak=DB.with_suffix(".json.reclass-bak"); bak.write_text(DB.read_text(encoding="utf-8"),encoding="utf-8")
        CACHE = ROOT/"outputs"/"_classify_cache.json"
        cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
        idx={p["id"]:p for p in db}
        for p,inds,reason in changes:
            t=idx[p["id"]]
            t["industryAll"]=False
            nonind=[x for x in t.get("tags",[]) if x not in INDG]  # 비업종 태그 보존
            t["tags"]=inds+nonind
            # 선순환 환류: 분류 캐시도 갱신 → 풀 리빌드(classify-llm.py) 시에도 유지
            prev=cache.get(p["id"], {})
            cache[p["id"]]={"goals": prev.get("goals", t.get("goals",[])),
                            "category": prev.get("category", t.get("category","")),
                            "industries": inds, "reason": reason or prev.get("reason","")}
        DB.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding="utf-8")
        CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"적용 완료 → DB+캐시 갱신 ({len(changes)}건), 백업: {bak.name}")
    elif not args.apply:
        print("(dry-run — 적용하려면 --apply)")

if __name__=="__main__":
    main()
