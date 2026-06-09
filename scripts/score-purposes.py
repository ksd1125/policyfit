#!/usr/bin/env python3
"""목적문 품질 검증 스코어러.

토스 스타일 목적문을 형식/내용/톤앤매너 3개 축으로 채점한다.
- 두 LLM(Codex/Claude) 생성본 비교
- 205건 Codex 생성본 전수 품질 검증
- 품질 미달분(70점 미만) 자동 검출 → 재생성 대상

사용법:
  python scripts/score-purposes.py --compare    # Claude vs Codex 비교
  python scripts/score-purposes.py --audit       # Codex 205건 전수 검증
  python scripts/score-purposes.py --db          # policyfit-db.json 전체 검증
"""

import json, sys, os, re, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "policyfit-db.json"
CODEX_CACHE = ROOT / "outputs" / "_purpose_cache_codex.json"
CLAUDE_PURPOSES = ROOT / "outputs" / "_claude_purposes.json"
COMPARE_SAMPLES = ROOT / "outputs" / "_compare_samples.json"

# ══════════════════════════════════════════════
# 품질 규칙 정의 (토스 스타일 가이드)
# ══════════════════════════════════════════════

# ── 프레임 1: 문제 해결형 (어려움 → 돕기) ──
# 공감/맥락 어휘 — "왜 필요한지" 배경
EMPATHY_WORDS = [
    "어려움", "어려운", "부담", "버거운", "빠듯한", "막막한", "막막해", "힘든", "힘들",
    "줄어", "위축", "침체", "피해", "여파", "부족", "걱정", "고민", "지친",
    "끊기", "끊긴", "흔들", "쉽지 않", "벅찬", "벅차", "더디", "막혀", "막막",
]

# ── 프레임 2: 기회 확대형 (활력 → 키우기) ──
# 관광 유치, 판로 개척, 환경 개선 등 — 긍정적 성장 동기
OPPORTUNITY_WORDS = [
    "활력", "활성화", "키우", "키울", "넓히", "늘려", "늘리", "살리", "살려",
    "높이", "더하", "다지", "다질", "발판", "기회", "도약", "성장 기반",
    "경쟁력", "안착", "튼튼", "북적", "이어가", "발돋움",
]

# 능동적 도움 표현 — 사용자 입장의 결과
HELP_VERBS = [
    "돕는", "도와", "마련하도록", "이어가도록", "이어갈", "시작하도록", "넘어", "넘도록",
    "일어서", "회복", "성장하도록", "키우", "키울", "찾도록", "만나", "지키",
    "덜어", "덜고", "낮춰", "풀고", "풀어", "북적", "안정", "넓히", "늘려",
    "살리", "높이", "다지", "더하", "이어", "만들", "갖추",
]

# 대상자 — 누구를 위한 것인지 (업종/주체 포함 확장)
TARGET_WORDS = [
    "소상공인", "소공인", "자영업", "기업", "창업자", "예비창업", "창업기업",
    "농가", "축산농가", "상인", "사장님", "스타트업", "벤처", "중소기업",
    "유통업", "제조업", "식품", "업소", "점포", "가게", "여행사", "관광객",
    "사업장", "사업자", "지역", "마을", "상권", "공방", "여행업", "농어업",
    "축산", "어가", "단체", "방문객", "근로자", "고용",
]

# 금지어 — 관공서 문체
FORMAL_BAD = [
    "공고합니다", "공고해요", "다음과 같이", "아래와 같이", "하오니", "바랍니다",
    "도모", "제고", "～", "신청하여", "참여 바", "모집합니다",
]

# 메타 응답 (LLM이 작업 거부/요청)
META_BAD = [
    "붙여주시면", "다듬어드리", "바꿔드리", "포함되지 않", "보이지 않", "빠져 있",
    "원문을", "작성해 드리", "말씀해 주", "제공해 주시", "알려주시면",
]


# ══════════════════════════════════════════════
# 문장 품질 검출기 (가독성/논리성/중언부언/비문)
# ══════════════════════════════════════════════

# 유의어 그룹 — 의미가 겹쳐 한 문장에 둘 다 쓰면 어색한 것만
# (※ "안정/안정적", "돕/지원"은 자연스러운 조합이라 제외)
SYNONYM_GROUPS = [
    ["성장", "발전", "도약"],
    ["활성화", "활력"],
    ["넓히", "늘려", "확대"],
]


def check_redundancy(t):
    """중언부언 검출 → 이슈 리스트.

    진짜 어색한 반복만 잡는다:
    - 동일 명사+조사 2회 (부담을...부담을)  ← 명백한 중복
    - 의미 겹치는 유의어 2개 (성장+발전)
    흔한 조합(돕+지원, 안정+안정적)은 정상으로 본다.
    """
    issues = []
    # 1) 동일 명사+조사 반복 (부담을...부담을) — 가장 명백한 중언부언
    nouns = re.findall(r"([가-힣]{2,})(?:을|를|이|가|은|는|에|의|로)", t)
    from collections import Counter
    nc = Counter(nouns)
    dup_nouns = [w for w, c in nc.items() if c >= 2 and w not in ("사업", "기업")]
    if dup_nouns:
        issues.append(f"단어반복: {dup_nouns}")

    # 2) 의미 겹치는 유의어 중복 (성장+발전 등)
    for group in SYNONYM_GROUPS:
        hits = [w for w in group if w in t]
        if len(hits) >= 2:
            issues.append(f"유의어중복: {hits}")
            break

    return issues


def check_grammar(t):
    """비문 검출 → 이슈 리스트"""
    issues = []
    # 1) 조사 연속 중복 (을을, 이가) — 단어 경계 고려
    if re.search(r"(을 을|를 를|이 가|은 는|에 에)", t):
        issues.append("조사오류")
    # 2) 어미 깨짐
    if re.search(r"하는는|이에요요|도록록|에요에요|사업사업", t):
        issues.append("어미중복")
    # 3) 목적-수단 구조 중복 ("~위해 ~위해", "~위한 ~위한")
    if len(re.findall(r"위해", t)) >= 2 or len(re.findall(r"위한", t)) >= 2:
        issues.append("위해/위한 중복")
    # 4) 미완성 종결 (조사로 끝남)
    stripped = t.rstrip(". ")
    if stripped.endswith(("을", "를", "의", "에", "과", "와", "로", "고")):
        issues.append("미완성 종결")
    # 5) 이중 공백/중점 깨짐
    if "  " in t or "··" in t or t.startswith(("·", ",", ".")):
        issues.append("문장부호 오류")
    return issues


def check_readability(t):
    """가독성 검출 → 이슈 리스트"""
    issues = []
    # 1) 중점(·) 과다 — 나열이 많으면 읽기 어려움
    dots = t.count("·")
    if dots >= 3:
        issues.append(f"중점 {dots}개 (나열 과다)")
    # 2) 관형절 3중첩 ("~하는 ~하는 ~하는")
    relative = len(re.findall(r"[가-힣](?:하는|되는|있는|없는|드는)\s", t))
    if relative >= 3:
        issues.append(f"관형절 {relative}중첩")
    # 3) 쉼표 과다
    if t.count(",") >= 3:
        issues.append("쉼표 과다")
    return issues


def check_logic(t):
    """논리성 검출 → 이슈 리스트.

    목적(왜)과 수단/결과(무엇을) 둘 다 없으면 논리 불완전.
    하나라도 있으면 통과 (대부분의 정상 문장).
    """
    issues = []
    has_goal = bool(re.search(r"위해|위한|도록|수\s*있|않도록|하려|하고자", t))
    has_means = bool(re.search(r"돕|지원|마련|연결|찾|키우|덜어|낮춰|높이|지키|"
                               r"넓히|늘려|살리|만들|이어|다지|누리|하는", t))
    # 둘 다 없을 때만 감점 (거의 없음)
    if not has_goal and not has_means:
        issues.append("목적-수단 구조 불명확")
    return issues


def score_purpose(text):
    """목적문을 0~100점으로 채점. (점수, 이슈리스트) 반환.

    100점(형식40+내용40+톤20)에서 문장품질 감점을 차감.
    """
    if not text:
        return 0, ["빈 텍스트"]

    score = 0
    issues = []
    t = text.strip()

    # ── 형식 (40점) ──
    # 해요체 종결 (15)
    if t.endswith(("사업이에요.", "사업이예요.")):
        score += 15
    elif t.endswith(("이에요.", "해요.", "드려요.", "어요.")):
        score += 10
        issues.append("종결: '사업이에요' 권장")
    else:
        issues.append("종결: 해요체 아님")

    # 길이 40~110 (10)
    n = len(t)
    if 45 <= n <= 100:
        score += 10
    elif 35 <= n <= 110:
        score += 6
        issues.append(f"길이 {n}자 (45~100 권장)")
    else:
        issues.append(f"길이 {n}자 부적합")

    # 한 문장 (5)
    if t.count(".") == 1 and "\n" not in t:
        score += 5
    else:
        issues.append("복수 문장")

    # 금지어 없음 (10)
    found_formal = [w for w in FORMAL_BAD if w in t]
    if not found_formal:
        score += 10
    else:
        issues.append(f"관공서 문체: {found_formal}")

    # ── 내용 (40점) ──
    # 메타응답 아님 (필수 — 있으면 0점 처리)
    found_meta = [w for w in META_BAD if w in t]
    if found_meta:
        return 0, [f"메타응답(작업거부): {found_meta}"]

    # 동기/맥락 (15) — 문제해결형(공감) 또는 기회확대형(성장) 둘 중 하나면 OK
    has_empathy = any(w in t for w in EMPATHY_WORDS)
    has_opportunity = any(w in t for w in OPPORTUNITY_WORDS)
    if has_empathy or has_opportunity:
        score += 15
    else:
        issues.append("배경/동기 표현 없음")

    # 능동적 도움/성장 (15)
    if any(w in t for w in HELP_VERBS):
        score += 15
    else:
        issues.append("도움/성장 표현 없음")

    # 대상자 명시 (10)
    if any(w in t for w in TARGET_WORDS):
        score += 10
    else:
        issues.append("대상자 불명확")

    # ── 톤앤매너 (20점) ──
    # 동기+도움 둘 다 (구체적 스토리) (10)
    has_help = any(w in t for w in HELP_VERBS)
    if (has_empathy or has_opportunity) and has_help:
        score += 10

    # 금액/법령 미포함 (10)
    if not re.search(r"「[^」]+」|\d+\s*(?:만원|억원|백만원)|제\d+조", t):
        score += 10
    else:
        issues.append("금액/법령 포함")

    # ── 문장 품질 감점 (가독성/논리성/중언부언/비문) ──
    red_iss = check_redundancy(t)
    gram_iss = check_grammar(t)
    read_iss = check_readability(t)
    logic_iss = check_logic(t)

    # 감점: 중언부언 -8, 비문 -10, 가독성 -5, 논리성 -10 (항목당)
    penalty = 0
    if red_iss:
        penalty += 8 * len(red_iss)
        issues += [f"[중언부언] {x}" for x in red_iss]
    if gram_iss:
        penalty += 10 * len(gram_iss)
        issues += [f"[비문] {x}" for x in gram_iss]
    if read_iss:
        penalty += 5 * len(read_iss)
        issues += [f"[가독성] {x}" for x in read_iss]
    if logic_iss:
        penalty += 10 * len(logic_iss)
        issues += [f"[논리성] {x}" for x in logic_iss]

    score = max(0, score - penalty)

    return score, issues


def grade(score):
    if score >= 85: return "A (우수)"
    if score >= 70: return "B (양호)"
    if score >= 50: return "C (보통)"
    return "D (미달)"


def cmd_compare():
    """Claude vs Codex 비교 채점"""
    samples = json.loads(COMPARE_SAMPLES.read_text(encoding="utf-8"))
    claude = json.loads(CLAUDE_PURPOSES.read_text(encoding="utf-8"))
    codex = json.loads(CODEX_CACHE.read_text(encoding="utf-8"))

    print("=" * 70)
    print("Claude vs Codex 목적문 품질 비교")
    print("=" * 70)

    c_total, x_total, n = 0, 0, 0
    for s in samples:
        pid = s["id"]
        codex_text = codex.get(pid, "")
        claude_text = claude.get(pid, "")
        if not codex_text:
            continue
        cx_score, cx_iss = score_purpose(codex_text)
        c_total += cx_score
        x_total += cx_score
        n += 1

        print(f"\n[{s['cat']}] {s['title']}")
        print(f"  Codex  {cx_score:3d}점 {grade(cx_score)}: {codex_text}")
        if claude_text and not pid.endswith(("_ir", "_structural")):
            cl_score, cl_iss = score_purpose(claude_text)
            c_total += cl_score - cx_score  # claude로 교체
            print(f"  Claude {cl_score:3d}점 {grade(cl_score)}: {claude_text}")

    print(f"\n{'='*70}")
    print(f"Codex 평균: {x_total/n:.1f}점 ({n}건)")


def cmd_audit():
    """Codex 생성본 전수 품질 검증"""
    codex = json.loads(CODEX_CACHE.read_text(encoding="utf-8"))

    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    failing = []
    total = 0
    # 문장 품질 항목별 카운트
    qual = {"중언부언": 0, "비문": 0, "가독성": 0, "논리성": 0}

    for pid, text in codex.items():
        sc, iss = score_purpose(text)
        total += sc
        grades[grade(sc)[0]] += 1
        for cat in qual:
            if any(cat in x for x in iss):
                qual[cat] += 1
        if sc < 85:
            failing.append((pid, sc, text, iss))

    n = len(codex)
    print("=" * 70)
    print(f"Codex 생성본 전수 품질 검증 ({n}건)")
    print("=" * 70)
    print(f"평균 점수: {total/n:.1f}점")
    print(f"  A(우수,85+): {grades['A']}건  B(70+): {grades['B']}건  "
          f"C(50+): {grades['C']}건  D(<50): {grades['D']}건")
    print(f"\n문장 품질 이슈 (가독성/논리성/중언부언/비문):")
    for cat, c in qual.items():
        print(f"  {cat}: {c}건")
    print(f"\n개선 필요(85점 미만): {len(failing)}건")
    for pid, sc, text, iss in failing[:15]:
        sent_iss = [x for x in iss if x.startswith("[")]
        print(f"  [{sc}점] {text[:55]}")
        if sent_iss:
            print(f"         {sent_iss}")


def cmd_db():
    """policyfit-db.json 전체 목적문 검증"""
    data = json.loads(DB_PATH.read_text(encoding="utf-8"))
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    total = 0
    failing = []
    for r in data:
        sc, iss = score_purpose(r["purpose"])
        total += sc
        grades[grade(sc)[0]] += 1
        if sc < 70:
            failing.append((r["id"], sc, r["purpose"]))

    n = len(data)
    print("=" * 70)
    print(f"policyfit-db.json 전체 목적문 품질 ({n}건)")
    print("=" * 70)
    print(f"평균: {total/n:.1f}점")
    for g in "ABCD":
        print(f"  {g}: {grades[g]}건 ({grades[g]*100//n}%)")
    print(f"\n개선 필요(70점 미만): {len(failing)}건")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--db", action="store_true")
    args = ap.parse_args()

    if args.compare:
        cmd_compare()
    elif args.audit:
        cmd_audit()
    elif args.db:
        cmd_db()
    else:
        cmd_audit()  # 기본


if __name__ == "__main__":
    main()
