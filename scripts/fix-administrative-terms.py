#!/usr/bin/env python3
"""목적문의 행정용어·맞춤법 정제.

2단계:
  1단계: 안전한 단어 치환 (편이장비 → 편의장비 등)
  2단계: 치환 후 문장이 어색해지면 LLM으로 자연스럽게 다듬기

사용:
  python scripts/fix-administrative-terms.py            # 적용
  python scripts/fix-administrative-terms.py --dry      # 미리보기만
  python scripts/fix-administrative-terms.py --no-llm   # 단순 치환만, LLM 검증 없음
"""
import json, sys, re, importlib.util, argparse, shutil
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
CACHE_CODEX = ROOT / "outputs" / "_purpose_cache_codex.json"
CACHE_CLAUDE = ROOT / "outputs" / "_claude_batch.json"


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


# ── 안전한 자동 치환 사전 ──
# 키: 정확히 매칭되어야 하는 용어 (단어 경계 포함)
# 값: 치환 표현
SAFE_REPLACEMENTS = [
    # 명백한 행정/오탈자
    ("편이장비", "편의장비"),
    ("편이시설", "편의시설"),
    ("경영애로", "경영 어려움"),
    ("자생력", "자립 능력"),

    # 한자어 → 일상어
    ("제고하고", "높이고"),
    ("제고하기", "높이기"),
    ("제고하는", "높이는"),
    ("제고하여", "높여"),
    ("제고해", "높여"),
    ("을 제고", "을 높이"),
    ("를 제고", "를 높이"),
    ("도모하고자", "돕기 위해"),
    ("도모하기 위해", "돕기 위해"),
    ("도모하기", "돕기"),
    ("도모하여", "돕고"),
    ("을 도모", "을 돕"),
    ("를 도모", "를 돕"),

    # 단순 띄어쓰기 / 깨진 토큰
    ("소상공 ", "소상공인 "),  # 끊긴 경우만
]


def fix_postpositions(text, replaced_words):
    """치환 후 어색해진 조사 정정 + 단어 반복 제거.

    화이트리스트 방식: 우리가 치환한 단어 바로 뒤의 조사만 정정.
    (전체 텍스트에 일반 규칙 적용 시 "지역물가"의 "가"를 조사로 오인할 위험)

    - 받침 있는 단어 뒤 "를/로/는/가/와" → "을/으로/은/이/과"
    - 치환된 단어가 반복되는 인접 패턴 제거
    """
    def has_batchim(syllable):
        if not (0xAC00 <= ord(syllable) <= 0xD7A3):
            return False
        return (ord(syllable) - 0xAC00) % 28 != 0

    mapping = {"를": "을", "로": "으로", "는": "은", "가": "이", "와": "과"}

    for w in replaced_words:
        if not w:
            continue
        # 받침 있으면 조사 정정
        if has_batchim(w[-1]):
            for wrong, correct in mapping.items():
                text = text.replace(w + wrong, w + correct)

        # 인접 의미 반복: 치환 단어의 끝 명사가 바로 뒤에서 다시 등장 시 단순화
        # "경영 어려움으로 어려움을 겪는" → "경영 어려움을 겪는"
        # "자립 능력으로 능력을 키우는" → "자립 능력을 키우는"
        last_noun = w.split()[-1]
        if len(last_noun) >= 2:
            text = re.sub(
                rf"{re.escape(w)}(?:으로|로|을|를|이|가|은|는)\s+{re.escape(last_noun)}(을|를|이|가|은|는|과|와|으로|로)",
                rf"{w}\1", text)

    return text


def apply_safe_replacements(text):
    """안전한 치환 적용 + 사후 조사·반복 정정."""
    original = text
    applied = []
    for old, new in SAFE_REPLACEMENTS:
        if old in text:
            text = text.replace(old, new)
            applied.append((old, new))
    # 사후 처리 — 치환 결과 단어 뒤 조사만 정정
    if applied:
        replaced_words = [new for _, new in applied]
        text = fix_postpositions(text, replaced_words)
    return text, applied


# ── LLM 검증 (선택) ──
LLM_VERIFY_PROMPT = """다음은 정책 사업 목적문이에요. 자동 치환된 결과인데 문장이 자연스러운지 확인해주세요.

치환 전: {before}
치환 후: {after}
적용 규칙: {rules}

평가:
- OK: 자연스러우니 그대로 둠
- POLISH: 의미는 맞지만 더 자연스럽게 다듬을 수 있음

POLISH인 경우 50~100자 한 문장으로 다시 작성:
- 해요체 (~사업이에요)
- "왜 필요한지" 배경 + 무엇으로 돕는지 수단
- 토스 앱 톤

응답 형식:
판정: OK | POLISH
다듬은 문장: (POLISH인 경우만)
"""


def llm_polish(before, after, rules, codexgen):
    """LLM에게 자연스러운지 확인하고 필요하면 재작성."""
    prompt = LLM_VERIFY_PROMPT.format(
        before=before, after=after,
        rules=", ".join(f"{o}→{n}" for o, n in rules))
    resp = codexgen.call_codex(prompt)
    if not resp:
        return after
    # 판정 파싱
    m = re.search(r"판정\s*[:：]\s*(OK|POLISH)", resp, re.IGNORECASE)
    verdict = m.group(1).upper() if m else "OK"
    if verdict == "OK":
        return after
    # POLISH — "다듬은 문장: ..." 추출
    m = re.search(r"다듬은\s*문장\s*[:：]\s*(.+?)(?:\n|$)", resp)
    if m:
        polished = m.group(1).strip().strip('"\'""')
        if polished.endswith(("이에요.", "해요.")) and 30 < len(polished) < 150:
            return polished
    return after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="미리보기만")
    ap.add_argument("--no-llm", action="store_true", help="LLM 검증 건너뛰기")
    args = ap.parse_args()

    data = json.loads(DB.read_text(encoding="utf-8"))
    sc = _load("sc", "score-purposes.py")

    # 후보 식별
    candidates = []
    for r in data:
        new_p, applied = apply_safe_replacements(r["purpose"])
        if applied:
            candidates.append((r, new_p, applied))

    print(f"=== 행정용어·맞춤법 정제 ({len(candidates)}건 후보) ===\n")
    if not candidates:
        print("자동 치환 대상 없음")
        return

    # LLM 검증/다듬기 (필요 시)
    codexgen = None
    if not args.no_llm and not args.dry:
        codexgen = _load("cg", "generate-via-codex-cli.py")

    # 백업
    if not args.dry:
        backup = DB.with_suffix(".json.fixterm-bak")
        shutil.copy2(DB, backup)
        print(f"백업: {backup.name}\n")

    # 캐시 로드
    codex_cache = json.loads(CACHE_CODEX.read_text(encoding="utf-8")) if CACHE_CODEX.exists() else {}
    claude_cache = json.loads(CACHE_CLAUDE.read_text(encoding="utf-8")) if CACHE_CLAUDE.exists() else {}

    fixed = 0
    polished = 0
    for r, swap_p, applied in candidates:
        prev_sc, _ = sc.score_purpose(r["purpose"])
        swap_sc, _ = sc.score_purpose(swap_p)

        final_p = swap_p
        if codexgen and len(applied) > 0:
            # LLM에게 자연스러운지 검증
            polished_p = llm_polish(r["purpose"], swap_p, applied, codexgen)
            if polished_p != swap_p:
                final_p = polished_p
                polished += 1

        final_sc, _ = sc.score_purpose(final_p)

        print(f"[{r['title'][:30]}]")
        print(f"  적용: {', '.join(f'{o}→{n}' for o, n in applied)}")
        print(f"  치환 {prev_sc}→{swap_sc}: {swap_p[:80]}")
        if final_p != swap_p:
            print(f"  다듬 {swap_sc}→{final_sc}: {final_p[:80]}")
        print()

        if not args.dry:
            r["purpose"] = final_p
            codex_cache[r["id"]] = final_p
            if r["id"] in claude_cache:
                claude_cache[r["id"]] = final_p
            fixed += 1

    # 저장
    if not args.dry:
        DB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        CACHE_CODEX.write_text(json.dumps(codex_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        CACHE_CLAUDE.write_text(json.dumps(claude_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"=== 완료 ===")
        print(f"치환: {fixed}건, LLM 다듬기: {polished}건")
        print(f"→ DB 및 캐시 저장")

        # 검증
        scs = [sc.score_purpose(r["purpose"])[0] for r in data]
        avg = sum(scs) / len(scs)
        a = sum(1 for s in scs if s >= 85)
        print(f"전체 품질: 평균 {avg:.1f}점, A등급 {a}/{len(data)} ({a*100//len(data)}%)")
    else:
        print(f"=== DRY-RUN 미리보기 ===")
        print(f"치환 대상: {len(candidates)}건 (--dry 모드, 저장 안 함)")


if __name__ == "__main__":
    main()
