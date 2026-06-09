#!/usr/bin/env python3
"""소상공인 무관 지원사업을 LLM로 판정해 smallBizRelevant=false 표시(앱에서 제외).

배경: 카페·미용실 같은 일반 소상공인/자영업자가 현실적으로 신청 불가한 공고
      (연구기관 전용, 조선·반도체 등 중후장대 산업 전용, 대기업/투자조합 전용 등)가
      섞여 있다. 키워드만으론 오탐('소공인복합지원센터'가 '연구소'에 걸림) → LLM 판단.

방식: 키워드로 후보를 좁힌 뒤(recall), 각 후보를 Gemini가 판정(precision).
      smallBizApplicable=false 인 것만 smallBizRelevant=false 로 표시.
      DB + _smallbiz_cache.json(환류, 리빌드 유지). 키는 .env.local 메모리.
"""
import json, sys, time, urllib.request, urllib.error, argparse
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs/policyfit-db.json"
CACHE = ROOT / "outputs/_smallbiz_cache.json"
# 후보 키워드(recall 넓게) — 실제 판정은 LLM
CAND = ['연구실','연구소','연구기관','대학교','산학협력','출연연','국책연구',
        '조선','선박','해양플랜트','반도체','방위산업','방산','원자력','우주발사','항공우주',
        '중공업','제철','정유','석유화학','소부장','뿌리산업','이차전지','수소','바이오','의약','신약',
        '중견기업','대기업','투자조합','투자운용','액셀러레이터','벤처투자','전문연구기관','규제자유특구','딥테크']

def key():
    for line in (ROOT/".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=",1)[1].strip()

def call(prompt, k):
    body=json.dumps({"contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0,"maxOutputTokens":150,"thinkingConfig":{"thinkingBudget":0},
            "responseMimeType":"application/json"}}).encode("utf-8")
    url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={k}"
    for a in range(5):
        try:
            d=json.loads(urllib.request.urlopen(urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"}),timeout=30).read())
            return json.loads("".join(x.get("text","") for x in d["candidates"][0].get("content",{}).get("parts",[])))
        except urllib.error.HTTPError as e:
            if e.code in (503,429) and a<4: time.sleep(6); continue
            return {"error":f"HTTP {e.code}"}
        except Exception as e:
            return {"error":str(e)[:60]}

def prompt(p):
    return "\n".join([
        "카페·미용실·편의점·식당·소규모 제조 같은 '일반 소상공인/자영업자/소기업'이 이 지원사업에 현실적으로 신청·수혜 가능한지 판정하세요.",
        "applicable=false 인 경우(소상공인 무관): 기업부설연구소·대학·연구기관 전용, 조선·반도체·방산·원자력 등 중후장대/첨단산업 기업 전용, 대기업·중견기업 전용, 투자조합·액셀러레이터 등 기관 모집.",
        "applicable=true 인 경우: 일반 소상공인/자영업자/소기업/소공인이 신청 가능(자금·판로·창업·고용·디지털 등 범용, 또는 일반 업종 대상). '소공인'은 소상공인이다(true).",
        '반드시 JSON만: {"applicable": true|false, "reason": "20자 이내"}',
        "",
        f"제목: {p.get('title')}",
        f"대상: {(p.get('targetDetail') or '')[:140]}",
        f"목적: {(p.get('purpose') or '')[:90]}",
    ])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true")
    ap.add_argument("--limit",type=int,default=0); a=ap.parse_args()
    k=key(); db=json.loads(DB.read_text(encoding="utf-8"))
    cache=json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    def is_cand(p):
        t=p.get('title','')+' '+(p.get('targetDetail') or '')+' '+(p.get('purpose') or '')
        return any(kw in t for kw in CAND)
    cands=[p for p in db if is_cand(p) and p["id"] not in cache]
    if a.limit: cands=cands[:a.limit]
    print(f"후보 {len(cands)}건 판정 (캐시 {len(cache)}건 보유, apply={a.apply})\n")
    nonrel=0
    for i,p in enumerate(cands,1):
        r=call(prompt(p), k)
        if r.get("error"): print(f"  [ERR {r['error']}] {p['title'][:30]}"); continue
        app=r.get("applicable"); reason=r.get("reason","")
        cache[p["id"]]={"applicable": bool(app), "reason": reason}
        if app is False:
            nonrel+=1; print(f"  [제외] {p['title'][:40]}  ({reason})")
        else:
            print(f"  [유지] {p['title'][:40]}  ({reason})")
        if i%10==0: CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
        time.sleep(4.3)
    CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"\n판정 완료. 이번 비적합 {nonrel}건. 캐시 총 {len(cache)}건.")
    if a.apply:
        idx={p["id"]:p for p in db}
        applied=0
        for pid,v in cache.items():
            if pid in idx:
                want = False if v.get("applicable") is False else None
                if want is False and idx[pid].get("smallBizRelevant")!=False:
                    idx[pid]["smallBizRelevant"]=False; applied+=1
                elif v.get("applicable") is True and "smallBizRelevant" in idx[pid]:
                    idx[pid].pop("smallBizRelevant",None)
        DB.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding="utf-8")
        total_excl=sum(1 for p in db if p.get("smallBizRelevant")==False)
        print(f"DB 적용: 이번 {applied}건 신규 제외표시. 전체 제외 {total_excl}건.")

if __name__=="__main__":
    main()
