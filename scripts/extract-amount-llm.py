#!/usr/bin/env python3
"""LLM(Codex) 기반 금액 구조 추출.

규칙 기반이 노이즈(매출액 기준·투자유치액·영업이익)에 약한 문제를 해결.
LLM이 원문을 문맥 판단해 [기업당 한도 / 총사업비 / 대상수]를 구조적으로 추출.

대상: 금액이 모호하거나 거대한 케이스 (총사업비 표기, 100억+, total_only 등).
explicit(명시 "기업당 N억")은 규칙으로 충분하므로 LLM 생략 가능(--all로 강제).

캐시: outputs/_amount_struct_cache.json — 재빌드 시 보존.

사용:
  python scripts/extract-amount-llm.py --test 3      # 3건 테스트
  python scripts/extract-amount-llm.py               # 대상 전체
  python scripts/extract-amount-llm.py --apply       # 캐시→DB 반영
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
MD_BASE = ROOT / "raw" / "markdown" / "20260601-224706"
CACHE = ROOT / "outputs" / "_amount_struct_cache.json"


def load_full_text(pbln_id):
    # 모든 runId 폴더에서 검색 (신규/e2e 공고도 포함). 최신 폴더 우선.
    folder = MD_BASE / pbln_id
    if not folder.is_dir():
        cands = sorted((ROOT / "raw" / "markdown").glob(f"*/{pbln_id}"),
                       key=lambda p: p.parent.name, reverse=True)
        if not cands:
            return ""
        folder = cands[0]
    parts = []
    detail = folder / "detail.md"
    if detail.exists():
        parts.append(detail.read_text(encoding="utf-8", errors="replace"))
    for md in sorted(folder.glob("*.md")):
        if md.name != "detail.md":
            try: parts.append(md.read_text(encoding="utf-8", errors="replace"))
            except: pass
    return "\n\n".join(parts)


def excerpt_money(text, max_len=2500):
    """금액 관련 구간 발췌 — '지원규모/지원내용/예산/한도/금액' 주변."""
    if len(text) <= max_len:
        return text
    # 금액 신호 키워드 위치들의 주변을 모음
    keywords = ["지원규모", "지원 규모", "지원내용", "지원 내용", "지원금액", "지원 금액",
                "예산", "사업비", "한도", "보조금", "지원한도", "모집규모", "선정규모",
                "억원", "백만원", "천만원", "개사", "업체당", "기업당"]
    spans = []
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text):
            spans.append((max(0, m.start() - 120), min(len(text), m.end() + 180)))
    if not spans:
        return text[:max_len]
    # 머지
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = []
    total = 0
    for s, e in merged:
        chunk = text[s:e]
        if total + len(chunk) > max_len:
            chunk = chunk[:max_len - total]
        out.append(chunk)
        total += len(chunk)
        if total >= max_len:
            break
    return " […] ".join(out)


PROMPT = """다음 정책 공고문에서 '지원 금액 구조'를 추출하세요. JSON만 출력하세요.

[공고 제목]
{title}

[공고문 발췌]
{excerpt}

추출 규칙(매우 중요):
1. perApplicant = 1개 기업/사업자/개인이 실제로 '받는' 지원금 총액.
   - "업체당/기업당/개사당 N억", "최대 N만원" 등 1인 기준 지급액.
   - 월 단위 지급이면 총 지급액으로 환산.
     예: "출산급여 월 30만원, 최대 3개월" → perApplicant는 90만원("월 30만원×3개월").
   - ⚠ 아래는 '받는 돈'이 아니므로 perApplicant에 절대 넣지 마세요:
     · 신청자격·제한 요건 (예: "매출액 1,200만원 이하 소상공인", "연소득 N원 미만")
     · 보증·융자 '한도'가 아닌 자격 기준 금액
   - 지원금이 명확하지 않으면 null (자격요건 숫자를 억지로 넣지 말 것).
2. total = 이 사업의 전체 예산("지원예산/총사업비/예산규모/국비 N억").
   - 주의: 아래는 예산이 아니므로 절대 total에 넣지 마세요.
     · 신청자격 매출액 기준 (예: "매출액 140억원 이하인 기업")
     · 기업 투자유치액/누적실적 (예: "투자 1,624억원 받은 창업기업")
     · 운영사·제3자의 영업이익/매출/자산 (예: "운영사 영업이익 575억원")
   - 진짜 사업 예산만. 없으면 null.
3. targetCount = 모집/선정 기업·업체 수 (정수).
   - 주의: 은행 수, 포상 부문 수, 직원 수는 제외.
   - 없으면 null.

핵심 판단: 여러 금액이 보이면 "신청자가 실제 지급받는 돈"만 perApplicant.
자격 제한·매출 기준·총예산은 별도 필드이거나 제외.

금액은 원화 정수로도 환산(억원=100000000, 천만원=10000000, 백만원=1000000, 만원=10000).

출력 형식(JSON 한 줄, 다른 텍스트 없이):
{{"perApplicant": "기업당 최대 3천만원" 또는 null, "perApplicantWon": 30000000 또는 null, "total": "1,000억원" 또는 null, "totalWon": 100000000000 또는 null, "targetCount": 36 또는 null, "reason": "한 줄 근거"}}
"""


def call_codex_json(prompt):
    """codex 호출 — JSON 응답 raw 반환. 스레드 안전(고유 out_file)."""
    out_file = str(ROOT / "outputs" / f"_codex_amt_{uuid.uuid4().hex}.txt")
    codex_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")
    try:
        if os.path.exists(out_file):
            os.remove(out_file)
        subprocess.run(
            [codex_path, "exec", "--skip-git-repo-check",
             "-c", "model_reasoning_effort=low",
             "-o", out_file, "-"],
            input=prompt.encode("utf-8"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180, shell=True,
        )
        if not os.path.exists(out_file):
            return None
        with open(out_file, encoding="utf-8") as f:
            txt = f.read().strip()
        os.remove(out_file)
        return txt
    except Exception as e:
        print(f"  [warn] codex error: {e}", file=sys.stderr)
        return None


def parse_json(txt):
    """응답에서 JSON 객체 추출."""
    if not txt: return None
    # ```json ... ``` 또는 { ... } 추출
    m = re.search(r"\{[^{}]*\"perApplicant\"[^{}]*\}", txt, re.DOTALL)
    if not m:
        m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        # 흔한 오류 정정 (null/None, 트레일링 콤마)
        s = m.group(0).replace("None", "null").replace("'", '"')
        s = re.sub(r",\s*}", "}", s)
        try:
            return json.loads(s)
        except Exception:
            return None


def select_targets(data, mode):
    """LLM 대상 선정.

    mode:
      priority — 거대금액 + 총사업비 표기만 (사용자 지적 핵심 ~40건)
      targets  — priority + 확인필요(금액 미상)
      all      — 전체
    """
    targets = []
    for r in data:
        lbl = r.get("amountLabel") or ""
        is_huge = bool(re.search(r"억원", lbl)) and _val(lbl) >= 10_000_000_000
        is_total = "총사업비" in lbl
        is_unknown = lbl in ("", "지원 규모 확인 필요")
        if mode == "all":
            targets.append(r)
        elif mode == "priority" and (is_huge or is_total):
            targets.append(r)
        elif mode == "targets" and (is_huge or is_total or is_unknown):
            targets.append(r)
    return targets


def _val(label):
    if not label: return 0
    rn = re.sub(r"\s+", "", label)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원|조원)", rn)
    if not m: return 0
    u = {"조원": 1_000_000_000_000, "억원": 100_000_000,
         "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try: return int(float(m.group(1).replace(",", "")) * u[m.group(2)])
    except: return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=int, help="N건만 테스트")
    ap.add_argument("--mode", choices=["priority", "targets", "all"], default="priority")
    ap.add_argument("--apply", action="store_true", help="캐시→DB 반영")
    ap.add_argument("--workers", type=int, default=1, help="병렬 워커 수")
    ap.add_argument("--ids", help="특정 공고 ID만 (쉼표구분, 강제 재처리)")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    # ── apply 모드: 캐시를 DB에 반영 ──
    if args.apply:
        backup = DB.with_suffix(".json.llmamt-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}\n")
        applied = 0
        for r in data:
            c = cache.get(r["id"])
            if not c: continue
            per = c.get("perApplicant")
            per_won = c.get("perApplicantWon")
            total = c.get("total")
            total_won = c.get("totalWon")
            tc = c.get("targetCount")
            # source 결정
            if per:
                source = "explicit_llm"
            elif total and tc and tc > 1:
                est = total_won // tc if total_won else None
                if est and est < 5_000_000_000:
                    per = f"약 {_fmt(est)} (총액÷대상수)"
                    per_won = est
                    source = "calculated_llm"
                else:
                    source = "total_only_llm"
            elif total:
                source = "total_only_llm"
            else:
                source = "none_llm"

            # 긴 1인 한도 라벨은 카드용으로 축약 (환산값 기반)
            if per and len(per) > 40 and per_won:
                per = f"최대 {_fmt(per_won)}"

            r["amountPerApplicant"] = per
            r["amountPerApplicantValue"] = per_won
            r["amountTotal"] = total
            r["amountTotalValue"] = total_won
            r["amountTargetCount"] = (f"{tc}개사" if tc else None)
            r["amountTargetCountValue"] = tc
            r["amountSource"] = source

            # LLM이 1인 한도·예산 모두 못 찾음(none_llm) →
            # 기존 amountLabel에 남은 거대 노이즈 금액(과거실적/투자유치액 등) 제거
            if source == "none_llm":
                r["amountLabel"] = "지원 규모는 공고 확인"
                r["amountValue"] = None
                r["amountSub"] = ""
            applied += 1
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {applied}건 DB 반영")
        return

    # ── 추출 모드 ──
    if args.ids:
        id_set = set(args.ids.split(","))
        targets = [r for r in data if r["id"] in id_set]
    else:
        targets = select_targets(data, args.mode)
    if args.test:
        targets = targets[:args.test]
    # 미처리만 (--ids는 강제 재처리)
    todo = [r for r in targets if args.test or args.ids or r["id"] not in cache]
    print(f"대상 {len(targets)}건 중 신규 {len(todo)}건 LLM 추출 (worker={args.workers})...\n")

    lock = threading.Lock()
    counter = {"done": 0, "fail": 0}
    total = len(todo)

    def process(r):
        text = load_full_text(r["id"])
        if not text:
            return r["id"], None
        prompt = PROMPT.format(title=r["title"], excerpt=excerpt_money(text))
        resp = call_codex_json(prompt)
        return r["id"], (parse_json(resp), resp)

    def handle_result(r, res):
        rid, payload = res
        with lock:
            if payload and payload[0]:
                cache[rid] = payload[0]
                counter["done"] += 1
                n = counter["done"] + counter["fail"]
                p = payload[0]
                print(f"[{n}/{total}] ✓ {r['title'][:38]} | 당:{str(p.get('perApplicant'))[:20]} 총:{p.get('total')}")
            else:
                counter["fail"] += 1
                n = counter["done"] + counter["fail"]
                print(f"[{n}/{total}] ✗ {r['title'][:38]}")
                if args.test and payload:
                    print(f"    raw: {(payload[1] or '')[:120]}")
            # 주기적 저장
            if counter["done"] % 10 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.workers <= 1:
        for r in todo:
            handle_result(r, process(r))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(process, r): r for r in todo}
            for fut in as_completed(futs):
                handle_result(futs[fut], fut.result())

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 캐시 저장: 성공 {counter['done']}건 / 실패 {counter['fail']}건 ({CACHE.name})")
    print(f"  적용: python scripts/extract-amount-llm.py --apply")


def _fmt(v):
    if v is None: return ""
    if v >= 100_000_000:
        n = v / 100_000_000
        return f"{int(n) if n == int(n) else round(n, 1)}억원"
    if v >= 10_000:
        return f"{v // 10_000:,}만원"
    return f"{v:,}원"


if __name__ == "__main__":
    main()
