#!/usr/bin/env python3
"""knowledge-db.json → policyfit-db.json 변환 어댑터.

정책핏 프론트엔드가 기대하는 스키마로 변환한다.
dday는 저장하지 않고 endDate만 저장 → 프론트에서 동적 계산.
"""

import json, re, sys, os
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
# 환경변수로 입출력/runId override 가능 (격리 테스트·재사용)
_RUN_ID = os.environ.get("E2E_RUN_ID", "20260601-224706")
INPUT = os.path.join(ROOT, "outputs", os.environ.get("E2E_KNOWLEDGE_OUT", "knowledge-db.json"))
OUTPUT = os.path.join(ROOT, "outputs", os.environ.get("E2E_POLICYFIT_OUT", "policyfit-db.json"))
MD_BASE = os.path.join(ROOT, "raw", "markdown", _RUN_ID)


# ══════════════════════════════════════════════
# 원본 공고문에서 사업목적 직접 추출
# detail.md의 ## 사업개요 → ☞ 이전 텍스트 = 사업의 본질/배경
# ══════════════════════════════════════════════

def _extract_print_purpose(pblancId):
    """print_*.md에서 (지원목적)/(사업목적) 텍스트를 추출.
    상세 공고문에만 있는 정확한 사업 목적 1줄.
    """
    pdir = os.path.join(MD_BASE, pblancId)
    if not os.path.exists(pdir):
        return None
    print_files = [f for f in os.listdir(pdir) if f.startswith("print_")]
    if not print_files:
        return None
    with open(os.path.join(pdir, print_files[0]), encoding="utf-8") as f:
        content = f.read()

    # (지원목적) / (사업목적) / (추진목적) 뒤 텍스트 추출
    for kw in ["지원목적", "사업목적", "추진목적"]:
        idx = content.find(kw)
        if idx < 0:
            continue
        after = content[idx + len(kw):]
        # ')' 이후 ~ 줄바꿈까지
        m = re.search(r"[)]\s*(.+?)(?:\n|$)", after)
        if m:
            text = m.group(1).strip()
            # 날짜/마감일 오추출 필터: "~ 2026.06.30" 같은 건 제외
            if re.match(r"^[~∼]?\s*\d{4}", text) or len(text) < 15:
                continue
            return re.sub(r"\s+", " ", text).strip()[:150]
    return None


def _extract_legal_basis(pblancId):
    """원본 공고문에서 법령 근거를 추출 (정책입안자용).
    Returns: list of 법령명 (예: ["중소기업진흥에 관한 법률", "소상공인기본법"])
    """
    detail_path = os.path.join(MD_BASE, pblancId, "detail.md")
    if not os.path.exists(detail_path):
        return []
    with open(detail_path, encoding="utf-8") as f:
        text = f.read()
    # 「법률명」 추출
    laws = re.findall(r"「([^」]+)」", text)
    # 중복 제거, 사업명(법/조례/규정이 아닌 것) 제외
    seen = set()
    result = []
    for law in laws:
        if law in seen:
            continue
        seen.add(law)
        # 법령인지 확인
        if re.search(r"법률|법$|조례|규정|시행령|시행규칙|기본법", law):
            result.append(law)
    return result[:5]  # 최대 5개


def _extract_purpose_core(raw_text):
    """사업개요 원문에서 '목적'에 해당하는 핵심구만 추출.

    4가지 패턴별 처리:
    1) 배경+목적: "~어려움을...위해 [사업명]을..." → 배경+목적부 전체
    2) 기관소개: "[기관]에서는 ~을 위해..." → "~을 위해" 부분
    3) 사업소개: "~을 위해 추진하는 [사업명]..." → "~을 위해" 앞까지
    4) 법령+공고: "「법」제N조...공고합니다" → 법령 제거 후 잔여
    """
    t = re.sub(r"\s+", " ", raw_text).strip()

    # ☞ 이전만 사용
    arrow = t.find("☞")
    if arrow > 0:
        t = t[:arrow].strip()

    # 기관 주어 제거: "(재)OO진흥원에서는/OO센터는/OO공단은 ~" → 목적만 남김
    t = re.sub(
        r"^\(?재?\)?\s*[가-힣A-Za-z·]+?"
        r"(?:테크노파크|진흥원|혁신센터|창조경제혁신센터|산업진흥원|경제진흥원"
        r"|정보산업진흥원|바이오산업진흥원|콘텐츠진흥원|문화재단|진흥회|중앙회"
        r"|센터|공단|재단|협회|공사|진흥공단|특별자치도|광역시|시청|군청|구청)"
        r"(?:은|는|이|가|에서는|에서|와|과|와\s*함께|과\s*함께)\s*",
        "", t
    )

    # "위하여 → 위해" 정규화 (패턴 매칭 일관성)
    t = t.replace("위하여", "위해").replace("하고자", "하기 위해")

    # 꼬리 안내문구 제거: "~공고합니다/바랍니다/하오니" 이후 전부 삭제
    for tail_pat in [r"(?:다음|아래)과 같이[\s\S]*$",
                     r"하오니[\s\S]*$", r"바라며[\s\S]*$",
                     r"공고합니다[\s\S]*$", r"바랍니다[\s\S]*$",
                     r"안내드립니다[\s\S]*$"]:
        t = re.sub(tail_pat, "", t).strip()

    # 법령 제거: 「법률명」 제N조...에 따라
    t = re.sub(r"「[^」]*(?:법률|법|조례|규정|시행령)[^」]*」\s*(?:제\d+조[^,]*(?:,\s*제\d+조[^,]*)?)?\s*(?:에\s*(?:따라|의거|의한|따른))?\s*", "", t)
    t = re.sub(r"「[^」]*(?:법률|법|조례|규정)[^」]*」", "", t)  # 잔여 법령
    # 사업명「」은 보존 (따옴표 변환)
    t = re.sub(r"「([^」]*)」", r"'\1'", t)

    # "~을/를 위해" 패턴에서 목적구 추출
    # 예: "중소기업의 경영 안정을 위해 추진하는..." → "중소기업의 경영 안정을 돕는 사업이에요"
    m = re.search(r"(.{10,80}?(?:을|를)\s*위해)", t)
    if m:
        purpose_part = m.group(1).strip()
        # 앞에 기관명 붙어있으면 제거
        purpose_part = re.sub(r"^.{0,30}?(?:에서는|센터는|재단은|진흥원은|공단은|진흥원의|공단이)\s*", "", purpose_part)
        if len(purpose_part) > 20:
            return purpose_part.rstrip(".") + " 진행하는 사업이에요."

    # "~(으)로" + 목적어 패턴
    m = re.search(r"(.{10,60}?(?:으로|로)\s*.{5,30}?(?:지원|강화|안정|활성화|도모|촉진|완화|해소))", t)
    if m:
        return m.group(1).strip().rstrip(".") + "하는 사업이에요."

    # 정리 후 그대로 반환
    t = t.strip().rstrip(",. ")
    if len(t) < 15:
        return None
    if len(t) > 120:
        cut = t[:120].rfind(".")
        if cut > 30:
            t = t[:cut + 1]
        else:
            t = t[:117] + "..."
    return t


def extract_purpose_from_raw(pblancId):
    """원본 공고문에서 사업목적 텍스트를 추출 (v4).

    우선순위:
    1) print_*.md의 (지원목적)/(사업목적) — 가장 정확
    2) detail.md 사업개요에서 정밀 파싱 — 핵심 목적구 추출
    """
    # 1) print_*.md
    print_purpose = _extract_print_purpose(pblancId)
    if print_purpose and len(print_purpose) >= 20:
        if not print_purpose.startswith(("* ", "- ", "※")):
            return print_purpose

    # 2) detail.md
    detail_path = os.path.join(MD_BASE, pblancId, "detail.md")
    if not os.path.exists(detail_path):
        return None
    with open(detail_path, encoding="utf-8") as f:
        text = f.read()
    idx = text.find("## 사업개요")
    if idx < 0:
        return None
    start = idx + len("## 사업개요")
    end = text.find("##", start)
    if end < 0:
        end = len(text)
    overview = text[start:end].strip()

    return _extract_purpose_core(overview)


# ══════════════════════════════════════════════
# 토스 스타일 변환 — 관공서 문체 → 친숙한 해요체
# ══════════════════════════════════════════════

def tossify(text):
    """관공서 공고문체를 토스 앱 스타일의 친숙한 해요체로 변환.

    5단계 파이프라인:
    1) 법령 인용 제거 (사업명은 보존)
    2) 공고 장식문구 제거
    3) 관공서 용어 → 일상어
    4) 합니다/입니다 → 해요체
    5) 조사 보정 + 정리
    """
    if not text or len(text) < 10:
        return text
    t = text

    # ── 1단계: 법령 vs 사업명 구분 후 처리 ──
    # 「」 안에 법/법률/조례/규정/시행령 → 법령 = 통째 삭제
    # 그 외 → 사업명 = 따옴표로 대체
    def replace_bracket(m):
        inner = m.group(1)
        if re.search(r"법률|법(?:\s|$|」)|조례|규정|시행령|시행규칙|기본법", inner):
            return ""  # 법령 삭제
        return f"'{inner}'"  # 사업명 보존

    t = re.sub(r"「([^」]*)」", replace_bracket, t)

    # 법조항 + 연결어 삭제: "제N조(...)에 따라/의거/의한"
    t = re.sub(
        r"제\d+조(?:의\d+)?(?:\([^)]*\))?"
        r"(?:\s*(?:및|,)\s*(?:같은\s*(?:법|조례)\s*(?:시행규칙\s*)?)?"
        r"제\d+조(?:의\d+)?(?:\([^)]*\))?)?"
        r"\s*(?:의?\s*규정에\s*따라|에\s*(?:따라|의거|의한|따른|의해))\s*",
        "", t
    )
    # 단독 "에 따라/의한" (법령 삭제 후 잔여)
    t = re.sub(r"^\s*에\s*(?:따라|의한|따른|의거)\s*", "", t)
    # "에 관한 법률/조례" 잔여
    t = re.sub(r"\s*에 관한 (?:법률|조례|규정)\s*", " ", t)

    # ── 2단계: 공고 장식문구 제거 ──
    # "~를 다음과/아래와 같이 공고/시행/모집..." + 뒤의 모든 텍스트 절단
    t = re.sub(r"(?:을|를)?\s*(?:다음과|아래와) 같이[\s\S]*$", ".", t)
    # "공고 합니다" (공백 포함 변형)
    t = re.sub(r"(?:을|를)?\s*공고\s*합니다\.?", ".", t)
    # "많은 참여/신청/관심 바랍니다/부탁드립니다"
    t = re.sub(r",?\s*(?:많은\s*)?(?:참여|신청|관심)(?:를|을)?\s*(?:부탁|바랍)니다\.?", ".", t)
    t = re.sub(r",?\s*관심\s*있는\s*(?:기업|업체|분)(?:들)?의\s*", "", t)
    # "~하오니/바라며" 이후 삭제
    t = re.sub(r"하오니[,\s].*$", ".", t)
    t = re.sub(r"바라며[,\s].*$", ".", t)

    # ── 3단계: 관공서 용어 → 일상어 (순서 중요: 긴 패턴 먼저) ──
    vocab = [
        ("담보력이 부족한", "담보가 부족한"),
        ("담보력 부족", "담보 부족"),
        ("경영애로를 해소", "경영 어려움을 해소"),
        ("경영애로", "경영 어려움"),
        ("경영정상화를", "경영 회복을"),
        ("경영정상화", "경영 회복"),
        ("자생력 강화를", "자립 능력 강화를"),
        ("자생력 강화", "자립 능력 강화"),
        ("자생력", "자립 능력"),
        ("경쟁력 제고 ", "경쟁력 강화 "),    # 공백 포함 → 조사 안 깨짐
        ("경쟁력 제고를", "경쟁력 강화를"),
        ("경쟁력 제고", "경쟁력 강화"),
        # 도모 — 모든 변형
        ("도모하고자 추진하는", "돕기 위해 진행하는"),
        ("도모하고자", "돕기 위해"),
        ("를 도모합니다", "를 돕는 사업이에요"),
        ("를 도모하기 위해", "를 돕기 위해"),
        ("를 도모하고", "를 돕고"),
        ("을 도모합니다", "을 돕는 사업이에요"),
        ("을 도모하기 위해", "을 돕기 위해"),
        ("을 도모하고", "을 돕고"),
        ("도모를 위한", "을 위한"),
        ("도모를 위해", "을 위해"),
        ("도모합니다", "돕는 사업이에요"),
        ("도모하기 위해", "돕기 위해"),
        ("도모하기위해", "돕기 위해"),
        ("도모하고", "돕고"),
        ("도모", "지원"),  # 최종 폴백
        # 어투 개선
        ("추진하고자", "하려고"),
        ("제공하고자", "제공하려고"),
        ("지원하고자", "지원하려고"),
        ("모집하고자", "모집하려고"),
        ("수행하고자", "하려고"),
        ("개최코자", "열려고"),
        ("위하여", "위해"),
        ("대하여", "대해"),
        ("시행하오니", "진행해요"),
    ]
    for old, new in vocab:
        t = t.replace(old, new)

    # ── 4단계: 합니다/입니다 → 해요체 ──
    endings = [
        (r"지원합니다", "지원해요"),
        (r"제공합니다", "제공해요"),
        (r"모집합니다", "모집해요"),
        (r"진행합니다", "진행해요"),
        (r"시행합니다", "시행해요"),
        (r"운영합니다", "운영해요"),
        (r"실시합니다", "실시해요"),
        (r"드립니다", "드려요"),
        (r"있습니다", "있어요"),
        (r"됩니다", "돼요"),
        (r"겠습니다", "겠어요"),
        (r"했습니다", "했어요"),
    ]
    for pat, rep in endings:
        t = re.sub(pat + r"\.?", rep + ".", t)

    # 일반 ~합니다/입니다 (위에서 안 잡힌 것)
    t = re.sub(r"(\w)합니다\.?", r"\1해요.", t)
    t = re.sub(r"(\w)입니다\.?", r"\1이에요.", t)

    # ── 5단계: 정리 ──
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\.(\s*\.)+", ".", t)      # 이중 마침표
    t = re.sub(r"^\s*[,.\"']\s*", "", t)   # 앞쪽 구두점/따옴표 잔여
    t = re.sub(r"'\s*'", "", t)            # 빈 따옴표
    t = re.sub(r"\(\s*\)", "", t)          # 빈 괄호
    t = re.sub(r"\s+([.,])", r"\1", t)     # 구두점 앞 공백
    t = re.sub(r"강화\s+을", "강화를", t)  # "강화 을" 조사 수정
    t = re.sub(r"회복\s*를", "회복을", t)  # "회복를" 조사 수정
    t = re.sub(r"\s+", " ", t).strip()
    # 따옴표만 남은 빈 문장 ("사업명".) → 유의미 내용 없음
    if re.match(r'^["\'].+["\']\.?\s*$', t) and len(t) < 60:
        return text  # 원본 반환하여 폴백

    # 결과가 너무 짧으면 원본 반환 (변환 실패)
    if len(t) < 15:
        return text

    # 불완전 문장 마무리 ("~을/를." → "~사업이에요.")
    t_stripped = t.rstrip(". ")
    if t_stripped.endswith(("을", "를", "의", "에", "과", "와", "으로")):
        t = t_stripped + " 지원하는 사업이에요."
    elif not t.endswith((".", "요", "요.")):
        t = t.rstrip(",. ") + "."

    # 120자 초과 시 문장 단위 절단
    if len(t) > 120:
        cut = t[:120].rfind(".")
        if cut > 30:
            t = t[:cut + 1]
        else:
            cut = t[:120].rfind(",")
            if cut > 30:
                t = t[:cut] + "."

    return t


# ── 목적(goal) 매핑 ──
PURPOSE_TO_GOAL = {
    "운전자금": "fund", "이자보전": "fund", "보증지원": "fund",
    "마케팅비": "sales", "온라인판로": "sales", "수출": "sales",
    "디자인·브랜딩": "sales",
    "사업화": "startup", "재료비": "startup",
    "인건비": "hr", "교육훈련": "hr",
    "시설개보수": "digital", "컨설팅": "fund",
    "인증취득": "fund",
}

TITLE_GOAL_KW = {
    "fund": ["자금", "융자", "대출", "보증", "보전", "금리", "운영", "경영안정", "일자리안정", "카드수수료", "세제", "공제", "보험료"],
    "sales": ["판로", "마케팅", "홍보", "수출", "해외", "입점", "라이브", "바우처", "전시", "박람회"],
    "digital": ["디지털", "스마트", "키오스크", "배달", "온라인", "정보화", "클라우드", "AI", "빅데이터", "자동화"],
    "startup": ["창업", "예비창업", "사업화", "재창업", "재도전", "청년창업", "사관학교", "보육"],
    "hr": ["고용", "채용", "인력", "인건비", "일자리", "직업훈련", "취업", "근로"],
}

# ── 카테고리 매핑 ──
def map_category(rec):
    subcat = rec.get("subcategory", "")
    cat = rec.get("category", "")
    title = rec.get("title", "")
    purposes = rec.get("support", {}).get("purposes") or []
    t = (title + " " + subcat).lower()

    if subcat in ("융자",) or "이자보전" in purposes:
        return "운영자금"
    if subcat == "보증" or "보증지원" in purposes:
        return "운영자금"
    if "인건비" in purposes or "고용" in t or "인력" in t or "일자리" in t or "채용" in t:
        return "고용·인건비"
    if subcat in ("온라인", "오프라인", "홍보지원") or "마케팅비" in purposes or "온라인판로" in purposes:
        return "판로·마케팅"
    if "디지털" in t or "스마트" in t or "정보화" in subcat or "키오스크" in t:
        return "디지털 전환"
    if cat == "창업" or "창업" in t or "사업화" in subcat:
        return "창업 지원"
    if "수출" in purposes or "해외" in t or "수출" in t or subcat.startswith("보험(수출"):
        return "수출·해외진출"
    if "재도전" in t or "재기" in t or "재창업" in t or "폐업" in t:
        return "재기·재도전"
    if "시설" in subcat or "환경" in t or "시설개보수" in purposes:
        return "시설·환경"
    if subcat == "컨설팅" or subcat == "교육" or "교육훈련" in purposes:
        return "교육·컨설팅"
    if "공제" in t or "세제" in t or "보험" in t or "안전" in t:
        return "안전망·세제"
    if "인증취득" in purposes:
        return "교육·컨설팅"
    if "디자인" in subcat:
        return "판로·마케팅"
    return "교육·컨설팅"

# ── goals 매핑 ──
def map_goals(rec):
    goals = set()
    purposes = rec.get("support", {}).get("purposes") or []
    for p in purposes:
        g = PURPOSE_TO_GOAL.get(p)
        if g:
            goals.add(g)
    title = (rec.get("title", "") + " " + rec.get("support", {}).get("summary", "")).lower()
    for g, kws in TITLE_GOAL_KW.items():
        if any(k in title for k in kws):
            goals.add(g)
    if not goals:
        cat = map_category(rec)
        fallback = {
            "운영자금": "fund", "고용·인건비": "hr", "판로·마케팅": "sales",
            "디지털 전환": "digital", "창업 지원": "startup", "수출·해외진출": "sales",
            "재기·재도전": "startup", "시설·환경": "fund", "교육·컨설팅": "fund",
            "안전망·세제": "fund",
        }
        goals.add(fallback.get(cat, "fund"))
    return sorted(goals)

# ── stages 매핑 ──
def map_stages(rec):
    target = rec.get("eligibility", {}).get("target", "")
    title = rec.get("title", "").lower()
    summary = rec.get("support", {}).get("summary", "").lower()
    combined = title + " " + summary + " " + target

    stages = set()
    if "예비창업" in combined or "창업 준비" in combined or "미창업" in combined:
        stages.add("pre")
    if "창업벤처" in target or "창업" in combined:
        stages.add("pre")
        stages.add("y1")
    if "3년 미만" in combined or "3년 이내" in combined:
        stages.add("y1")
        stages.add("y13")
    if "7년 미만" in combined or "7년 이내" in combined or "5년 이내" in combined:
        stages.add("y1")
        stages.add("y13")
        stages.add("y3")

    if not stages:
        if "소상공인" in target or "중소기업" in target:
            stages = {"y1", "y13", "y3"}
        elif "창업벤처" in target:
            stages = {"pre", "y1"}
        else:
            stages = {"y1", "y13", "y3"}
    return sorted(stages)

# ── regions 매핑 ──
REGION_MAP = {
    "공통": "any", "서울": "seoul",
    "경기": "gyeonggi", "인천": "gyeonggi",
    "부산": "metro", "대구": "metro", "광주": "metro",
    "대전": "metro", "울산": "metro", "세종": "metro",
}

def map_regions(rec):
    region = rec.get("region", "공통")
    if region in REGION_MAP:
        return [REGION_MAP[region]]
    return ["local"]

# ── tags (업종) 매핑 ──
def map_tags(rec):
    title = rec.get("title", "").lower()
    summary = rec.get("support", {}).get("summary", "").lower()
    restrictions = rec.get("eligibility", {}).get("industryRestrictions") or []
    combined = title + " " + summary + " ".join(restrictions)

    tag_kw = {
        "food": ["음식", "식당", "외식", "카페", "요식", "분식", "치킨", "주점", "베이커리", "급식", "외식업"],
        "retail": ["도소매", "유통", "상점", "마트", "편의점", "소매", "도매", "시장", "상가"],
        "online": ["온라인", "쇼핑몰", "플랫폼", "이커머스", "인터넷", "전자상거래"],
        "maker": ["제조", "공장", "기술", "생산", "소공인", "가공", "부품"],
        "service": ["서비스", "미용", "학원", "세탁", "수리", "교육", "의료", "헬스"],
    }
    tags = set()
    for tag, kws in tag_kw.items():
        if any(k in combined for k in kws):
            tags.add(tag)
    if not tags:
        tags = {"food", "retail", "service", "online", "maker", "etc"}
    return sorted(tags)

# ── 금액 파싱 ──
def _label_to_won(label):
    """라벨의 단위를 인식해 원화값으로 환산 (정렬용). normalize와 동일 규칙."""
    if not label:
        return None
    s = label.replace(",", "").replace(" ", "")
    won = 0.0
    used = False
    for pat, mult in [("조", 1e12), ("천억", 1e11), ("억", 1e8),
                      ("천만", 1e7), ("백만", 1e6), ("만", 1e4), ("천원", 1e3)]:
        m = re.search(r"([\d.]+)" + pat, s)
        if m:
            won += float(m.group(1)) * mult
            s = s[:m.start()] + s[m.end():]
            used = True
    return int(round(won)) if used else None


def parse_amount(rec):
    amt = rec.get("support", {}).get("amount")
    if not amt:
        return None, "지원 규모 확인 필요", ""
    max_str = amt.get("max") or ""
    raw = amt.get("raw") or ""

    # 단위 인식 환산 (선두 숫자 그대로 쓰던 버그 수정)
    value = _label_to_won(max_str)

    label = max_str if max_str else "지원 규모 확인 필요"
    sub = raw if raw != max_str else ""
    return value, label, sub

# ── 신청 기간 / endDate ──
def parse_period(rec):
    app = rec.get("application", {})
    period_str = app.get("period", "")
    period_type = app.get("periodType", "")

    if period_type == "always_open" or "상시" in period_str:
        return "상시 접수", None

    match = re.search(r'(\d{4}-\d{2}-\d{2})\s*$', period_str.strip())
    if not match:
        match = re.search(r'~\s*(\d{4}-\d{2}-\d{2})', period_str)
    if match:
        return period_str, match.group(1)
    return period_str or "기간 확인 필요", None

# ── eligible 매핑 ──
def map_eligible(rec):
    quality = rec.get("quality", {}).get("grade", "")
    docs = rec.get("application", {}).get("documents") or []
    conditions = rec.get("eligibility", {}).get("conditions") or []
    exclusions = rec.get("eligibility", {}).get("exclusions") or []

    if quality == "detailed" and len(exclusions) <= 2:
        return "able"
    if quality in ("detailed", "moderate"):
        return "check"
    return "need"

# ── prepare 매핑 ──
# 즉시 발급 가능한 일반 행정서류 → have(이미 갖고 있을 가능성)
COMMON_DOCS = {"사업자등록증", "사업자 등록증", "신분증", "대표자 신분",
               "통장사본", "통장 사본", "주민등록등본", "등기부등본",
               "임대차계약서", "납세증명", "재직증명", "4대보험"}

# 서류명이 아니라 유의사항/제외사항/조건 텍스트를 가리키는 신호어
PREPARE_EXCLUDE_KW = ("제외", "불가", "이후", "마감", "협약", "결격", "평가",
                      "보완", "우대", "가점", "감점", "환수", "중복지원", "해약")

def _is_doc_label(label):
    """제출서류명인지 판별 — 유의사항/문장형 파편이면 False."""
    if len(label) > 40:
        return False
    if label.count(" ") >= 3:                                  # 공백 많으면 문장
        return False
    if label.count("(") + label.count(",") + label.count("·") >= 2:  # 괄호·콤마 多 = 문장
        return False
    if any(k in label for k in PREPARE_EXCLUDE_KW):            # 유의사항 신호어
        return False
    if re.search(r"(경우|때|시|함|음)$", label):               # 종결형 = 문장
        return False
    return True

def map_prepare(rec):
    docs = rec.get("application", {}).get("documents") or []
    items = []
    seen = set()
    for d in docs[:8]:
        d_clean = d.strip()
        if not d_clean or not _is_doc_label(d_clean):
            continue
        if d_clean in seen:
            continue
        seen.add(d_clean)
        is_common = any(c in d_clean for c in COMMON_DOCS)
        items.append({"label": d_clean, "status": "have" if is_common else "need"})
    if not items:
        items.append({"label": "사업자등록증", "status": "have"})
        items.append({"label": "신청서 (공고 확인 필요)", "status": "need"})
    return items

# ── steps 매핑 ──
def map_steps(rec):
    raw = rec.get("application", {}).get("steps") or []
    steps = []
    for s in raw[:8]:
        s = s.strip()
        if len(s) < 3:                                    # 너무 짧은 파편
            continue
        if re.match(r"^\s*\d+\s*[-–—~.]*\s*$", s):          # "12 -", 숫자+기호만
            continue
        if not re.search(r"[가-힣A-Za-z]", s):              # 한글/영문 없음 = 파편
            continue
        steps.append(s)
        if len(steps) >= 6:
            break
    if steps:
        return steps
    method = rec.get("application", {}).get("method", "")
    if method:
        return [method]
    return ["공고 확인 후 신청"]

# ── match (기본 점수) ──
def base_match(rec):
    quality = rec.get("quality", {}).get("grade", "")
    conf = rec.get("quality", {}).get("purposeConfidence", "")
    score = 50
    if quality == "detailed":
        score += 25
    elif quality == "moderate":
        score += 15
    if conf == "high":
        score += 10
    elif conf == "medium":
        score += 5
    amt = rec.get("support", {}).get("amount")
    if amt and amt.get("max"):
        score += 5
    return min(99, score)

# ── note ──
def make_note(rec):
    exclusions = rec.get("eligibility", {}).get("exclusions") or []
    contact = rec.get("contact", {})
    parts = []
    if exclusions:
        parts.append(exclusions[0][:80])
    phone = contact.get("phone")
    if phone:
        parts.append(f"문의: {phone}")
    if not parts:
        parts.append("공고 상세 내용을 반드시 확인하세요.")
    return " / ".join(parts)


# ══════════════════════════════════════════════
# SUMMARY 파싱 — 대상/지원내용/목적 분리
# ══════════════════════════════════════════════

def parse_summary(summary):
    """support.summary → (대상 텍스트, 지원내용 텍스트) 분리.
    원문 패턴: '[대상/자격] / [지원내용/금액]' (94%가 이 형태)
    """
    if not summary:
        return "", ""
    if " / " in summary:
        parts = summary.split(" / ", 1)
        return parts[0].strip(), parts[1].strip()
    if " - " in summary:
        parts = summary.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", summary.strip()


def shorten_target(target_text, rec):
    """대상자 텍스트 → 짧은 명사구 (카드 표시용)"""
    elig_target = rec.get("eligibility", {}).get("target", "")
    combined = (target_text or "") + " " + elig_target

    for kw in ["소상공인", "소공인", "예비창업자", "청년", "여성기업",
               "사회적기업", "농업인", "중견기업", "벤처기업"]:
        if kw in combined:
            return kw
    if "창업" in combined and ("3년" in combined or "7년" in combined or "미만" in combined):
        return "창업기업"
    if "중소기업" in combined:
        return "중소기업"
    if "창업" in combined:
        return "창업기업"
    return "중소기업·소상공인"


# ══════════════════════════════════════════════
# PURPOSE v2 — 공고별 특화 목적문 생성
# 전략: 제목(지역) + 대상 + 지원내용 구체 키워드 + 금액
# → 71종 → 690종으로 고유도 10배 향상
# ══════════════════════════════════════════════

def _extract_region(title):
    """제목에서 [지역명] 추출"""
    m = re.match(r"^\[([^\]]+)\]\s*", title or "")
    return m.group(1) if m else None

def _extract_specifics(benefits, title):
    """지원내용+제목에서 이 공고만의 구체 키워드를 추출 (최대 2개)"""
    b = (benefits or "").lower()
    t = (title or "").lower()
    items = [
        ("이차보전", "이자 보전"), ("이자지원", "이자 지원"), ("이자", "이자 지원"),
        ("보증료", "보증료 지원"), ("보증", "자금 보증"),
        ("멘토링", "멘토링"), ("IR", "IR·투자 유치"), ("투자", "투자 유치"),
        ("컨설팅", "경영 컨설팅"), ("진단", "경영 진단"),
        ("입점", "온라인 입점"), ("라이브커머스", "라이브커머스"), ("스마트스토어", "스마트스토어"),
        ("마케팅", "마케팅"), ("홍보", "홍보"), ("광고", "광고"),
        ("디자인", "디자인 개발"), ("브랜딩", "브랜드 개발"), ("시제품", "시제품 제작"),
        ("R&D", "R&D"), ("기술개발", "기술 개발"),
        ("특허", "특허·IP"), ("인증", "인증 취득"),
        ("인테리어", "인테리어 개선"), ("간판", "간판 교체"), ("리모델링", "리모델링"),
        ("키오스크", "키오스크 도입"), ("배달", "배달앱 지원"), ("자동화", "자동화 시설"),
        ("수출", "수출 지원"), ("해외", "해외 진출"), ("바이어", "바이어 매칭"),
        ("고용보험", "고용보험료"), ("사회보험", "사회보험료"), ("인건비", "인건비"),
        ("채용", "채용 지원"), ("교육", "교육"), ("훈련", "역량 훈련"),
    ]
    found = []
    seen = set()
    for kw, label in items:
        if kw in b or kw in t:
            if label not in seen:
                found.append(label)
                seen.add(label)
            if len(found) >= 2:
                break
    return found

def _amount_short(rec):
    """금액 라벨 (짧은 형태, 괄호에 넣을 용)"""
    amt = rec.get("support", {}).get("amount")
    if not amt:
        return None
    mx = amt.get("max", "")
    if not mx:
        return None
    # 비정상 금액 필터 (1000억 이상 = 오파싱)
    nums = re.findall(r"[\d,]+", mx.replace(",", ""))
    if nums:
        try:
            v = int(nums[0])
            if "백만원" in mx:
                v *= 100
            if v > 100000:  # 1000억원 이상은 비정상
                return None
        except ValueError:
            pass
    return mx

def _postposition(word):
    """한글 조사 '을/를' 선택 (받침 유무)"""
    if not word:
        return "을"
    last = ord(word[-1])
    if 0xAC00 <= last <= 0xD7A3:
        return "을" if (last - 0xAC00) % 28 != 0 else "를"
    return "을"  # 비한글이면 기본 '을'

# 서브카테고리 → 폴백 동사구
_SUBCAT_VERB = {
    "융자": "운영자금 융자", "보증": "자금 보증",
    "온라인": "온라인 판로 개척", "오프라인": "판로·마케팅",
    "홍보지원": "홍보·마케팅", "컨설팅": "경영 컨설팅",
    "사업화지원": "창업 사업화", "예비창업자지원": "창업 준비·교육",
    "창업공간지원": "창업 공간 지원", "창업정보제공": "창업 정보·네트워킹",
    "교육": "역량 강화 교육", "시설/입지지원": "시설 개선·환경 정비",
    "정보화지원": "디지털 전환", "디자인/상품화/사업화": "제품 개발·사업화",
    "보험(수출+무역)": "수출·무역 보험",
}


def generate_purpose(rec, target_text, benefits):
    """v2: 지역 + 대상 + 구체 항목 + 금액 → 공고별 특화 목적문"""
    target = shorten_target(target_text, rec)
    region = _extract_region(rec.get("title", ""))
    specifics = _extract_specifics(benefits, rec.get("title", ""))
    amount = _amount_short(rec)
    subcat = rec.get("subcategory", "")

    # 주어: [지역] 대상
    subj = f"{region} {target}" if region else target
    pp = _postposition(subj)  # 을/를

    # 술어: 구체 항목 or 서브카테고리 폴백
    if specifics:
        joined = "·".join(specifics)
        # "~지원" 으로 끝나는 항목이면 "지원" 중복 방지
        verb = joined if joined.endswith("지원") else joined + " 지원"
    else:
        verb = _SUBCAT_VERB.get(subcat, "경영 지원")

    purpose = f"{subj}{pp} 위한 {verb}"

    # 금액 (여유 있으면 괄호 추가)
    if amount and len(purpose) < 32:
        purpose += f" ({amount})"

    return purpose


# ── 메인 변환 ──
def convert(rec):
    amount_value, amount_label, amount_sub = parse_amount(rec)
    period, end_date = parse_period(rec)

    raw_summary = rec.get("support", {}).get("summary") or ""
    target_text, benefits = parse_summary(raw_summary)
    target_short = shorten_target(target_text, rec)

    # 목적: 원본 공고문 추출 → 토스 변환 → 빈약하면 v2 폴백
    raw_purpose = extract_purpose_from_raw(rec["id"])
    if raw_purpose:
        purpose = tossify(raw_purpose)
        # 변환 후 너무 짧거나 제목/사업명만 남으면 v2 폴백
        stripped = purpose.strip('"\'. ')
        is_titleonly = (stripped.endswith(("계획", "공고", "사업", "변경", "수정"))
                        and "위해" not in purpose and "돕" not in purpose)
        is_quoted = purpose.lstrip().startswith(('"', "'", "“", "‘")) and len(stripped) < 60
        if len(purpose) < 25 or is_titleonly or is_quoted:
            purpose = generate_purpose(rec, target_text, benefits)
    else:
        purpose = generate_purpose(rec, target_text, benefits)

    return {
        "id": rec["id"],
        "title": rec["title"],
        "org": rec.get("institution", ""),
        "executor": rec.get("executor", ""),
        "category": map_category(rec),
        "tags": map_tags(rec),
        "stages": map_stages(rec),
        "goals": map_goals(rec),
        "regions": map_regions(rec),
        # ▼ 분리된 필드 (핵심 변경)
        "purpose": purpose,                        # 목적 (자동 생성, 1줄)
        "targetShort": target_short,               # 대상 축약 (카드용)
        "targetDetail": target_text[:200],         # 대상 상세 (시트용)
        "benefits": benefits[:200],                # 지원내용 (시트용)
        "summary": raw_summary[:200],              # 원문 (폴백용)
        # ▲
        "amountLabel": amount_label,
        "amountValue": amount_value,
        "amountSub": amount_sub,
        "period": period,
        "endDate": end_date,
        "match": base_match(rec),
        "eligible": map_eligible(rec),
        "prepare": map_prepare(rec),
        "steps": map_steps(rec),
        "note": make_note(rec),
        "legalBasis": _extract_legal_basis(rec["id"]),  # 정책입안자용 법령 근거
        "url": rec.get("url", ""),
        # status: endDate 기준 (UI는 dday로 동적 판단하지만 데이터 정합성 유지)
        "status": "마감" if (end_date and end_date < date.today().isoformat()) else "모집중",
    }

# ══════════════════════════════════════════════
# 후처리: 목적문 품질 검증 + 자동 수정
# ══════════════════════════════════════════════

def _is_target_text(text):
    """목적이 아니라 대상자 설명인지 판별"""
    t = text.strip()
    # "~에 소재/보유한/등록한 중소기업" 패턴
    if re.match(r"^.{0,15}(소재|영업중인|사업장을|보유한|등록을|등록한)", t):
        return True
    # 대상자 명사로만 끝나는 경우
    if re.match(r"^[가-힣\s·ㆍ()]*?(중소기업|소상공인|사업자|법인)\s*[.]?\s*$", t):
        return True
    return False


def postprocess_purpose(policy, records_map):
    """목적문 품질 검증 & 자동 수정.

    문제 유형:
    1) 대상자 텍스트가 목적에 들어간 경우 → benefits에서 재추출 or v2 폴백
    2) 너무 짧은 (<25자) → benefits 키워드 보강
    3) 마침표 안 끝남 → 추가
    """
    p = policy["purpose"]
    pid = policy["id"]

    # 1) 대상자 텍스트가 목적에 있으면 → benefits 기반 재생성
    if _is_target_text(p):
        rec = records_map.get(pid)
        if rec:
            summary = rec.get("support", {}).get("summary") or ""
            target_text, benefits = parse_summary(summary)
            policy["purpose"] = generate_purpose(rec, target_text, benefits)
            return "fix:target→v2"

    # 2) 짧은 목적 보강: benefits 키워드 추가
    if len(p) < 25:
        benefits = policy.get("benefits", "")
        amount = policy.get("amountLabel", "")
        if benefits and len(benefits) > 10:
            # 지원내용에서 핵심 동사구 추출하여 보강
            short_benefit = benefits[:60].split(" - ")[0].split(" ※")[0].strip()
            if short_benefit and len(short_benefit) > 10:
                policy["purpose"] = p.rstrip(". ") + " — " + short_benefit + "."
                return "fix:보강"

    # 3) 마침표 마무리
    if not p.endswith((".", "요", "요.")):
        policy["purpose"] = p.rstrip(",. ") + "."

    return None


def main():
    with open(INPUT, encoding="utf-8") as f:
        records = json.load(f)

    print(f"Input: {len(records)} records from knowledge-db.json")

    # records lookup
    records_map = {r["id"]: r for r in records}

    policies = [convert(r) for r in records]

    # 후처리: 목적문 품질 자동 수정
    fix_counts = {}
    for p in policies:
        result = postprocess_purpose(p, records_map)
        if result:
            fix_counts[result] = fix_counts.get(result, 0) + 1

    if fix_counts:
        print(f"\nPurpose auto-fix:")
        for k, v in sorted(fix_counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}건")

    cat_dist = {}
    goal_dist = {}
    for p in policies:
        cat_dist[p["category"]] = cat_dist.get(p["category"], 0) + 1
        for g in p["goals"]:
            goal_dist[g] = goal_dist.get(g, 0) + 1

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)

    print(f"\nOutput: {len(policies)} policies → {OUTPUT}")
    print(f"\nCategory distribution:")
    for c, n in sorted(cat_dist.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")
    print(f"\nGoal distribution:")
    for g, n in sorted(goal_dist.items(), key=lambda x: -x[1]):
        print(f"  {g}: {n}")

if __name__ == "__main__":
    main()
