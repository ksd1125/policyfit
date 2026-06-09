/**
 * policyfit-config.js
 * ─────────────────────────────────────────────
 * 순수 JS — 질문 설정, 유형 프로필, 매칭 로직, 유틸
 * Babel 불필요. index.html에서 일반 <script>로 로드.
 */

/* ══════════════════════════════════════════════
   GLOBAL STORE — fetch 후 채워짐
   ══════════════════════════════════════════════ */
window.POLICIES = [];

/* ══════════════════════════════════════════════
   USER TYPES & PROFILES
   ══════════════════════════════════════════════ */
const USER_TYPES = [
  { id: "owner",    label: "소상공인·자영업자", desc: "이미 사업을 운영 중이에요", icon: "shop" },
  { id: "prestart", label: "예비 창업자",       desc: "창업을 준비하고 있어요",   icon: "bulb" },
];

const TYPE_PROFILE = {
  owner: {
    prefill: {},
    goals: ["fund", "sales", "digital", "hr"],
    stages: ["y1", "y13", "y3"],
    note: "운영 중인 사업장 기준으로 자금·판로·고용 지원을 찾아드려요.",
  },
  prestart: {
    prefill: { stage: "pre" },
    goals: ["startup", "fund", "digital"],
    note: "아직 창업 전이니 창업 자금·공간·교육 위주로 찾아드려요.",
  },
};

/* ══════════════════════════════════════════════
   QUESTIONS (진단 4단계)
   ══════════════════════════════════════════════ */
const QUESTIONS = [
  {
    id: "goal", q: "지금 가장 급한 건 무엇인가요?",
    hint: "이것만 골라도 결과를 볼 수 있어요",
    options: [
      { id: "fund",    label: "운영자금·대출" },
      { id: "sales",   label: "매출·판로 확대" },
      { id: "digital", label: "디지털 전환" },
      { id: "startup", label: "창업 자금·공간" },
      { id: "hr",      label: "인건비·고용" },
    ],
  },
  {
    id: "stage", q: "사업 단계는 어디쯤인가요?",
    hint: "지원금 자격을 가르는 핵심 기준이에요",
    options: [
      { id: "pre", label: "창업 준비 중" },
      { id: "y1",  label: "1년 미만" },
      { id: "y13", label: "1~3년차" },
      { id: "y3",  label: "3년 이상" },
    ],
  },
  {
    id: "industry", q: "어떤 업종이세요?",
    hint: "선택 사항이에요 · 더 정확해져요",
    options: [
      { id: "food",    label: "음식·외식" },
      { id: "retail",  label: "도소매·유통" },
      { id: "service", label: "생활·서비스" },
      { id: "online",  label: "온라인·플랫폼" },
      { id: "maker",   label: "제조·기술" },
      { id: "etc",     label: "기타" },
    ],
  },
  {
    id: "region", q: "사업장이 어디인가요?",
    hint: "선택 사항이에요 · 지역 전용 사업도 찾아드려요",
    options: [
      { id: "seoul",    label: "서울" },
      { id: "gyeonggi", label: "경기·인천" },
      { id: "metro",    label: "광역시" },
      { id: "local",    label: "그 외 지역" },
      { id: "any",      label: "상관없어요" },
    ],
  },
];

/* 조건 레이블 (결과 화면용) */
const CONDLABEL = {
  industry: { food: "음식·외식", retail: "도소매·유통", service: "생활·서비스",
              online: "온라인·플랫폼", maker: "제조·기술", etc: "기타" },
  stage:    { pre: "창업 준비", y1: "1년 미만", y13: "1~3년차", y3: "3년 이상" },
  goal:     { fund: "운영자금", sales: "판로 확대", digital: "디지털 전환",
              startup: "창업 자금", hr: "고용·인건비" },
  region:   { seoul: "서울", gyeonggi: "경기·인천", metro: "광역시",
              local: "그 외", any: "전국" },
};

/* 카테고리→아이콘 */
const CAT_ICON = {
  "운영자금": "coins", "고용·인건비": "users", "판로·마케팅": "chart",
  "디지털 전환": "monitor", "창업 지원": "bulb", "안전망·세제": "shield",
  "시설·환경": "store", "교육·컨설팅": "cap", "수출·해외진출": "globe",
  "재기·재도전": "refresh",
};

/* ══════════════════════════════════════════════
   UTILITY
   ══════════════════════════════════════════════ */

/** endDate → D-day (동적 계산, 저장 금지) */
function computeDday(endDate) {
  if (!endDate) return null;
  const end = new Date(endDate + "T23:59:59");
  const now = new Date();
  const diff = Math.ceil((end - now) / (1000 * 60 * 60 * 24));
  return diff < 0 ? -1 : diff;
}

/** 유형별 질문 필터 */
function questionsForType(ut) {
  const prof = TYPE_PROFILE[ut] || {};
  return QUESTIONS.map(q => {
    if (q.id === "goal" && prof.goals)
      return { ...q, options: q.options.filter(o => prof.goals.includes(o.id)) };
    if (q.id === "stage" && prof.stages)
      return { ...q, options: q.options.filter(o => prof.stages.includes(o.id)) };
    return q;
  });
}

/* ══════════════════════════════════════════════
   MATCHING ENGINE  v2 — 슬롯 교차 비율 점수
   ══════════════════════════════════════════════

   설계 원칙:
   ─────────
   "적합 사업" = 사용자가 답한 조건을 모두 충족하는 사업.
   점수(0~99) = "답한 슬롯 중 이 사업이 몇 %를 충족하는가"

   슬롯별 처리:
   ┌────────┬────────┬─────────────────────────────────────┐
   │ 슬롯   │ 성격   │ 로직                                │
   ├────────┼────────┼─────────────────────────────────────┤
   │ goal   │ 하드   │ 불일치 → 제외 (0점)                 │
   │ stage  │ 하드   │ 불일치 → 제외 (0점)                 │
   │ region │ 하드   │ 불일치 → 제외 (any면 통과)          │
   │industry│ 소프트 │ 일치→가산, 불일치→감점(제외는 안 함) │
   └────────┴────────┴─────────────────────────────────────┘

   점수 산출 (답한 슬롯 수에 비례):
   - 각 슬롯이 답변되면 가용 점수 풀에 기여
   - goal 충족 → 40점, stage 충족 → 30점, region 충족 → 15점
   - industry: 특정 업종 태그 일치 → 10점, 전업종(6종) → 5점, 불일치 → 0점
   - 데이터 품질 보너스: p.match를 0~4점으로 정규화
   - 총점 = (획득 / 가용) × 95 + 4  → 4~99 범위

   답한 슬롯이 적을수록 가용 총점이 낮아서
   "1개만 답한 결과"와 "4개 다 답한 결과"의 점수 스케일이 같아짐.
   ══════════════════════════════════════════════ */

// 금액 표시 헬퍼 — window에 명시 등록 (text/babel 모듈 스코프에서도 접근 보장)
window.amountVerified = function (p) {
  const label = p.amountPerApplicant || p.amountLabel || "";
  if (/공고 확인|확인 필요|규모 확인/.test(label)) return false;
  return ["explicit_llm", "calculated_llm", "total_only_llm"].includes(p.amountSource) && !!label;
};
window.amountText = function (p, sentence) {
  const label = p.amountPerApplicant || p.amountLabel || "";
  const isPlaceholder = !label || /공고 확인|확인 필요|규모 확인/.test(label);
  if (sentence) return isPlaceholder ? "지원 규모는 공고를 확인해 주세요." : `${label}을 지원하며`;
  return isPlaceholder ? "공고 확인 필요" : label;
};

const SPECIAL_TARGET_RULES = [
  { id: "disabled", label: "장애인", user: ["장애인", "장애인기업"], policy: ["장애인", "장애인기업"], detailPattern: /장애인(기업| 예비창업자| 중 | 대상| 확인서|창업자)/ },
  { id: "youth", label: "청년", user: ["청년", "청년창업", "청년기업"], policy: ["청년", "청년기업", "청년창업"], detailPattern: /청년(대표|창업자|기업 인증|기업인| 대상| 소상공인)|19세|39세/ },
  { id: "women", label: "여성", user: ["여성", "여성기업", "여성창업", "출산"], policy: ["여성", "여성기업", "여성농업인", "출산"], detailPattern: /여성(기업|소상공인|농업인|대표|창업자)|출산/ },
  { id: "social", label: "사회적경제", user: ["사회적경제", "사회적 기업", "사회적기업", "협동조합", "마을기업", "자활기업", "소셜벤처"], policy: ["사회적경제", "사회적 기업", "사회적기업", "협동조합", "마을기업", "자활기업", "소셜벤처"], detailPattern: /사회적경제(조직|기업)|사회적기업|\(예비\)사회적기업|협동조합|마을기업|자활기업|소셜벤처/ },
  { id: "tourism", label: "관광·여행사", user: ["관광", "여행사", "여행업", "관광업"], policy: ["관광", "여행사", "여행업", "단체관광객"], detailPattern: /여행사|관광업|관광사업|단체관광객/ }
];

function detectUserSpecialTargets(text) {
  const t = (text || "").toLowerCase();
  return SPECIAL_TARGET_RULES
    .filter(rule => rule.user.some(k => t.includes(k.toLowerCase())))
    .map(rule => rule.id);
}

function policySpecialTargets(p) {
  const strong = `${p.title || ""} ${p.targetShort || ""}`.toLowerCase();
  const detail = `${p.targetDetail || ""}`.toLowerCase();
  const hits = [];
  for (const rule of SPECIAL_TARGET_RULES) {
    const strongHit = rule.policy.some(k => strong.includes(k.toLowerCase()));
    const detailHit = rule.detailPattern && rule.detailPattern.test(p.targetDetail || "");
    if (strongHit || detailHit) hits.push(rule.id);
  }
  return hits;
}

function specialTargetAllowed(p, answers) {
  const policyTargets = policySpecialTargets(p);
  if (!policyTargets.length) return true;
  const userTargets = (answers && answers._matchMeta && answers._matchMeta.specialTargets) || [];
  return policyTargets.some(t => userTargets.includes(t));
}

function detectLifecycleIntent(text) {
  const t = text || "";
  if (/예비|준비\s*중|준비중|창업\s*전|오픈\s*전|시작\s*전|창업\s*준비|개업\s*준비/.test(t)) return "prestart";
  if (/운영\s*중|운영중|운영하|영업\s*중|영업중|장사|매장|가게|사업장|자영업|소상공인/.test(t)) return "operating";
  return "";
}

function policyLifecycleTargets(p) {
  const text = `${p.title || ""} ${p.category || ""} ${p.targetShort || ""} ${p.targetDetail || ""}`;
  const targets = [];
  if (/예비창업|창업\s*전|창업예정|창업\s*준비/.test(text) || ((p.stages || []).length && (p.stages || []).every(s => s === "pre"))) {
    targets.push("prestart");
  }
  if (/스타트업|창업기업|초기창업|기술창업|오픈이노베이션|창업\s*지원/.test(text) || p.category === "창업 지원") {
    targets.push("startup");
  }
  return [...new Set(targets)];
}

function lifecycleAllowed(p, answers) {
  const lifecycle = answers && answers._matchMeta && answers._matchMeta.lifecycle;
  if (lifecycle !== "operating") return true;
  if (answers.goal === "startup" || answers.stage === "pre") return true;
  const targets = policyLifecycleTargets(p);
  if (targets.includes("prestart")) return false;
  if (targets.includes("startup") && (p.goals || []).includes("startup")) return false;
  return true;
}

function policyRegionHints(p) {
  const text = `${p.title || ""} ${p.org || ""} ${p.executor || ""}`;
  const hints = new Set();
  if (/서울|서울특별시/.test(text)) hints.add("seoul");
  if (/경기|경기도|인천|인천광역시/.test(text)) hints.add("gyeonggi");
  if (/부산|대구|대전|광주|울산|세종|부산광역시|대구광역시|대전광역시|광주광역시|울산광역시|세종특별자치시/.test(text)) hints.add("metro");
  if (/강원|충북|충남|충청|전북|전남|전라|경북|경남|경상|제주|강원특별자치도|충청북도|충청남도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도/.test(text)) hints.add("local");
  return [...hints];
}

const SPECIFIC_REGION_PATTERNS = [
  { id: "seoul", group: "seoul", re: /서울|서울특별시/ },
  { id: "incheon", group: "gyeonggi", re: /인천|인천광역시/ },
  { id: "gyeonggi", group: "gyeonggi", re: /경기|경기도/ },
  { id: "busan", group: "metro", re: /부산|부산광역시/ },
  { id: "daegu", group: "metro", re: /대구|대구광역시/ },
  { id: "daejeon", group: "metro", re: /대전|대전광역시/ },
  { id: "gwangju", group: "metro", re: /광주|광주광역시/ },
  { id: "ulsan", group: "metro", re: /울산|울산광역시/ },
  { id: "sejong", group: "metro", re: /세종|세종특별자치시/ },
  { id: "gangwon", group: "local", re: /강원|강원특별자치도/ },
  { id: "chungbuk", group: "local", re: /충북|충청북도/ },
  { id: "chungnam", group: "local", re: /충남|충청남도/ },
  { id: "jeonbuk", group: "local", re: /전북|전북특별자치도/ },
  { id: "jeonnam", group: "local", re: /전남|전라남도/ },
  { id: "gyeongbuk", group: "local", re: /경북|경상북도/ },
  { id: "gyeongnam", group: "local", re: /경남|경상남도/ },
  { id: "jeju", group: "local", re: /제주|제주특별자치도/ },
];

function specificRegionIds(text) {
  const t = text || "";
  const isGyeonggiGwangju = /(?:경기|경기도)\s*광주|(?:경기|경기도).{0,12}광주시|\[경기\].{0,20}광주/.test(t);
  const explicitGwangjuMetro = /광주광역시|\[광주\]/.test(t);
  return SPECIFIC_REGION_PATTERNS
    .filter(x => {
      if (x.id === "gwangju" && isGyeonggiGwangju && !explicitGwangjuMetro) return false;
      return x.re.test(t);
    })
    .map(x => x.id);
}

function policySpecificRegionIds(p) {
  return specificRegionIds(`${p.title || ""} ${p.org || ""} ${p.executor || ""} ${p.targetDetail || ""}`);
}

function requestedSpecificRegionIds(regionMeta) {
  if (!regionMeta) return [];
  return specificRegionIds(`${regionMeta.standard || ""} ${regionMeta.alias || ""}`);
}

function policyRegionCompatible(p, regionMeta) {
  const policyIds = policySpecificRegionIds(p);
  if (!policyIds.length || !regionMeta) return true;
  const requestedIds = requestedSpecificRegionIds(regionMeta);
  if (!requestedIds.length) return true;
  return policyIds.some(id => requestedIds.includes(id));
}

function regionMatchMode(answers) {
  const { industry, goal, region, _regionMode, _matchMeta } = answers || {};
  const explicitNational = _matchMeta && _matchMeta.region && _matchMeta.region.intent === "national";
  if (region === "any" && explicitNational) return "national_only";
  if (!region || region === "any") return "none";
  if (_regionMode) return _regionMode;
  return (industry || goal) ? "national_first" : "strict";
}

function comparePolicyMatches(a, b) {
  const ra = a._regionOrder || 0;
  const rb = b._regionOrder || 0;
  if (ra !== rb) return rb - ra;
  return (b.pscore || 0) - (a.pscore || 0);
}

function computeMatches(answers) {
  const { industry, stage, goal, region, _matchMeta } = answers || {};
  const rmode = regionMatchMode(answers);

  return POLICIES.map(p => {
    /* ── 하드 필터 (불일치 = 즉시 제외) ── */
    if (goal && !p.goals.includes(goal))   return { ...p, pscore: 0 };
    if (stage && !p.stages.includes(stage)) return { ...p, pscore: 0 };
    if (!specialTargetAllowed(p, answers)) return { ...p, pscore: 0 };
    if (!lifecycleAllowed(p, answers)) return { ...p, pscore: 0 };
    const rs = p.regions || ["any"];
    const hintedRegions = policyRegionHints(p);
    const isPseudoNational = rs.includes("any") && hintedRegions.length > 0;
    const isNational = rs.includes("any") && !isPseudoNational;
    const isRegional = region && region !== "any" && (rs.includes(region) || hintedRegions.includes(region));
    const isSpecificRegional = isRegional && _matchMeta && _matchMeta.region && regionSpecificHit(p, _matchMeta.region);
    const regionCompatible = !_matchMeta || !_matchMeta.region || policyRegionCompatible(p, _matchMeta.region);
    if (rmode === "national_only" && !isNational) return { ...p, pscore: 0 };
    if (region && region !== "any") {
      if (!regionCompatible) return { ...p, pscore: 0 };
      if (rmode === "strict") {
        if (!isRegional) return { ...p, pscore: 0 };
      } else if (!isNational && !isRegional) {
        return { ...p, pscore: 0 };
      }
    }

    /* ── 슬롯별 점수 적립 ── */
    let earned = 0;   // 획득 점수
    let pool   = 0;   // 가용 총점

    // 1) goal (40점) + 목적 특화 보너스 (0~8점)
    //    사업의 goals가 적을수록 해당 목적에 특화된 사업
    //    goals=1 → +8, goals=2 → +5, goals=3 → +2, 4+ → 0
    if (goal) {
      pool += 48;
      earned += 40;
      const goalSpec = [0, 8, 5, 2, 0, 0][Math.min(p.goals.length, 5)];
      earned += goalSpec;
    }

    // 2) stage (30점)
    if (stage) { pool += 30; earned += 30; }   // 하드필터 통과 = 충족

    // 3) region (15점)
    if (region && region !== "any") {
      pool += 15; earned += 15;                // 하드필터 통과 = 충족
      if (rmode === "strict" && _matchMeta && _matchMeta.region && _matchMeta.region.alias !== _matchMeta.region.label) {
        pool += 8;
        if (regionSpecificHit(p, _matchMeta.region)) earned += 8;
      }
    }

    // 4) industry (12점, 소프트)
    //    업종 무관 사업(industryAll/전업종 태그) → 10점 (모든 업종에 적합)
    //    특정 업종 일치 → 12점 (딱 맞음, 약간 우대)
    //    특정 업종 불일치 → 0점 (변별)
    if (industry) {
      pool += 12;
      // industryAll 명시 필드(LLM 분류) 우선. 없는 레거시 레코드만 태그 수 휴리스틱.
      const allInd = p.industryAll === true
        || (p.industryAll === undefined && p.tags && p.tags.length >= 6);
      if (allInd) {
        earned += 10;                          // 업종 무관 = 누구나 적합
      } else if (p.tags.includes(industry)) {
        earned += 12;                          // 특정 업종 정확 일치
      }
      // 특정 업종인데 불일치 → 0점 (변별력)
    }

    // 5) 데이터 품질 보너스 (0~4점, 항상 가용)
    pool += 4;
    earned += Math.round(Math.max(0, ((p.match || 50) - 50) / 50 * 4));

    /* ── 비율 점수 (4~99) ──
       pool엔 항상 데이터품질 4점이 포함되므로 pool>=4 (무답변도 4점). */
    const pscore = Math.max(4, Math.min(99, Math.round((earned / pool) * 95 + 4)));
    const regionOrder = rmode === "national_first"
      ? (isNational ? 3 : (isSpecificRegional ? 2.5 : 2))
      : (rmode === "strict" ? 1 : (rmode === "national_only" ? 3 : (rmode === "none" && isNational ? 1 : 0)));
    const regionClass = rmode === "national_first"
      ? (isNational ? "national" : "regional")
      : (rmode === "strict" ? "regional-only" : (rmode === "national_only" ? "national-only" : (rmode === "none" ? (isNational ? "national" : "regional") : "none")));

    return { ...p, pscore, _regionOrder: regionOrder, _regionClass: regionClass };
  })
  .filter(p => p.pscore > 0)
  .sort(comparePolicyMatches);
}

/** 선택지별 결과 건수 (칩에 표시) */
function optionCount(answers, qid, optId) {
  return computeMatches({ ...answers, [qid]: optId }).length;
}

/* ══════════════════════════════════════════════
   SEED PARSER (자유 입력 → 자동 채움)
   ══════════════════════════════════════════════ */
const GOAL_KW = {
  fund:    ["운영자금","운전자금","시설자금","자금","대출","융자","돈","경영안정","긴급","보증",
            "빚","급전","현금","장사 밑천","밑천","돈줄","자본","사업비","이자","빌리"],
  sales:   ["판로","매출","판매","마케팅","홍보","수출","라이브","스토어","온라인 판매",
            "광고","판촉","박람회","전시회","입점","해외진출","바이어","거래처","손님"],
  digital: ["키오스크","디지털","배달","스마트","테이블오더","포스","비대면",
            "앱","웹","온라인화","자동화","무인","ai","인공지능","스마트공장","데이터"],
  startup: ["창업","예비창업","사업화","초기창업","아이디어","공간","사무실",
            "시작","오픈","개업","법인","사업자등록","스타트업","재창업","아이템"],
  hr:      ["고용","직원","인건비","채용","알바","보험","4대보험",
            "사람","일손","구인","노무","산재","최저임금","근로자","인력"],
};
/* 상권 챗봇 사전 기반 업종 표준화 테이블.
   사용자 표현(alias)을 상권 표준 업종명으로 한 번 정규화한 뒤 정책핏의 6개 그룹으로 압축한다. */
const INDUSTRY_MATCH_TABLE = {
  aliases: {
    "고기집": "돼지고기 구이/찜", "고깃집": "돼지고기 구이/찜", "삼겹살": "돼지고기 구이/찜", "삼겹살집": "돼지고기 구이/찜",
    "소고기집": "소고기 구이/찜", "닭갈비": "닭/오리고기 구이/찜", "오리고기": "닭/오리고기 구이/찜",
    "백반집": "백반/한정식", "한정식": "백반/한정식", "한식집": "기타 한식 음식점", "밥집": "백반/한정식",
    "분식집": "김밥/만두/분식", "김밥집": "김밥/만두/분식", "칼국수집": "국수/칼국수", "국수집": "국수/칼국수",
    "카페": "카페", "커피": "카페", "커피집": "카페", "커피숍": "카페", "빵집": "빵/도넛", "베이커리": "빵/도넛",
    "치킨집": "치킨", "중국집": "중국집", "중식당": "중국집", "마라탕": "마라탕/훠궈", "횟집": "횟집", "초밥집": "일식 회/초밥",
    "술집": "요리 주점", "주점": "요리 주점", "호프집": "요리 주점", "햄버거": "버거", "버거집": "버거",
    "편의점": "편의점", "동네마트": "슈퍼마켓", "마트": "슈퍼마켓", "슈퍼": "슈퍼마켓", "과일가게": "채소/과일 소매업",
    "옷가게": "의류 소매업", "의류": "의류 소매업", "화장품": "화장품 소매업", "약국": "약국", "꽃집": "꽃집",
    "병원": "일반병원", "치과": "치과의원", "한의원": "한의원", "미용실": "미용실", "미장원": "미용실",
    "네일": "네일숍", "헬스": "헬스장", "헬스클럽": "헬스장", "피시방": "PC방", "pc방": "PC방",
    "세탁소": "세탁소", "빨래방": "셀프 빨래방", "학원": "입시·교과학원", "스터디카페": "독서실/스터디 카페",
    "온라인": "온라인 판매", "쇼핑몰": "온라인 판매", "스마트스토어": "온라인 판매", "쿠팡": "온라인 판매", "이커머스": "온라인 판매",
    "제조": "제조업", "공장": "제조업", "소공인": "제조업", "가공": "제조업", "부품": "제조업", "기술": "기술 서비스"
  },
  standardToGroup: {
    food: ["카페","빵/도넛","치킨","버거","김밥/만두/분식","국수/칼국수","백반/한정식","기타 한식 음식점","돼지고기 구이/찜","소고기 구이/찜","닭/오리고기 구이/찜","요리 주점","중국집","마라탕/훠궈","횟집","일식 회/초밥","기타 일식 음식점","음식점"],
    retail: ["편의점","슈퍼마켓","채소/과일 소매업","의류 소매업","화장품 소매업","약국","꽃집","소매업","도소매","유통"],
    service: ["일반병원","치과의원","한의원","미용실","네일숍","헬스장","PC방","세탁소","셀프 빨래방","입시·교과학원","독서실/스터디 카페","서비스업"],
    online: ["온라인 판매"],
    maker: ["제조업","기술 서비스"]
  },
  fallbackKeywords: {
    food:    ["음식","식당","외식","카페","요식","분식","치킨","주점","베이커리","호프","술집","배달음식","음식점"],
    retail:  ["도소매","유통","상점","마트","소매","편의점","의류","잡화","판매점"],
    online:  ["온라인","쇼핑몰","플랫폼","스마트스토어","쿠팡","네이버","인스타","이커머스"],
    maker:   ["제조","공장","기술","생산","가공","부품","소공인","제조업"],
    service: ["서비스","미용","학원","헬스","세탁","네일","피트니스","수리","청소","교육"],
  }
};
// 사업 단계 — 명확도 순(pre→y1→y13→y3)
const STAGE_KW = {
  pre:  ["예비","준비 중","준비중","예정","계획","아직","창업 전","오픈 전","시작 전"],
  y1:   ["1년 미만","막 시작","갓 시작","신규","최근 오픈","개업","갓 창업","올해 시작"],
  y13:  ["1~3년","1-3년","2년차","3년차","2년 됐","3년 됐","몇 년"],
  y3:   ["3년 이상","5년","10년","오래","베테랑","수년","오랫동안","장기"],
};
// 전국 지역 표준화 테이블. 정책 DB의 broad region(seoul/gyeonggi/metro/local/any)에 맞춘다.
const REGION_MATCH_TABLE = {
  anyKeywords: ["전국", "전국구", "전지역", "전체 지역", "지역무관", "지역 무관", "어디든", "상관없", "상관 없"],
  groups: {
    seoul: ["서울", "서울특별시"],
    gyeonggi: ["경기", "경기도", "인천", "인천광역시"],
    metro: ["부산", "부산광역시", "대구", "대구광역시", "대전", "대전광역시", "광주", "광주광역시", "울산", "울산광역시", "세종", "세종특별자치시", "광역시"],
    local: ["강원", "강원특별자치도", "충청", "충북", "충청북도", "충남", "충청남도", "전라", "전북", "전북특별자치도", "전남", "전라남도", "경상", "경북", "경상북도", "경남", "경상남도", "제주", "제주특별자치도", "지방", "도내", "군"]
  },
  // 전국 시군구/생활권 별칭. value는 사용자가 말한 지역의 표준 표현이다.
  aliases: {
    "서울 강남": "서울특별시 강남구", "강남구": "서울특별시 강남구", "강남": "서울특별시 강남구",
    "서울 강동": "서울특별시 강동구", "강동구": "서울특별시 강동구", "서울 강북": "서울특별시 강북구", "강북구": "서울특별시 강북구",
    "서울 강서": "서울특별시 강서구", "강서구": "서울특별시 강서구", "관악구": "서울특별시 관악구", "광진구": "서울특별시 광진구",
    "구로구": "서울특별시 구로구", "금천구": "서울특별시 금천구", "노원구": "서울특별시 노원구", "도봉구": "서울특별시 도봉구",
    "동대문구": "서울특별시 동대문구", "동작구": "서울특별시 동작구", "마포구": "서울특별시 마포구", "서대문구": "서울특별시 서대문구",
    "서초구": "서울특별시 서초구", "성동구": "서울특별시 성동구", "성북구": "서울특별시 성북구", "송파구": "서울특별시 송파구",
    "양천구": "서울특별시 양천구", "영등포구": "서울특별시 영등포구", "용산구": "서울특별시 용산구", "은평구": "서울특별시 은평구",
    "종로구": "서울특별시 종로구", "서울 중구": "서울특별시 중구", "중랑구": "서울특별시 중랑구",

    "인천 강화": "인천광역시 강화군", "인천 계양": "인천광역시 계양구", "계양구": "인천광역시 계양구",
    "인천 남동": "인천광역시 남동구", "남동구": "인천광역시 남동구", "미추홀구": "인천광역시 미추홀구",
    "인천 부평": "인천광역시 부평구", "부평구": "인천광역시 부평구", "인천 서구": "인천광역시 서구",
    "연수구": "인천광역시 연수구", "인천 중구": "인천광역시 중구", "옹진군": "인천광역시 옹진군",

    "수원": "경기도 수원시", "성남": "경기도 성남시", "고양": "경기도 고양시", "용인": "경기도 용인시",
    "부천": "경기도 부천시", "안산": "경기도 안산시", "안양": "경기도 안양시", "남양주": "경기도 남양주시",
    "화성": "경기도 화성시", "평택": "경기도 평택시", "의정부": "경기도 의정부시", "시흥": "경기도 시흥시",
    "파주": "경기도 파주시", "김포": "경기도 김포시", "광명": "경기도 광명시", "경기 광주": "경기도 광주시", "광주시": "경기도 광주시",
    "군포": "경기도 군포시", "하남": "경기도 하남시", "오산": "경기도 오산시", "양주": "경기도 양주시",
    "이천": "경기도 이천시", "구리": "경기도 구리시", "안성": "경기도 안성시", "포천": "경기도 포천시",
    "의왕": "경기도 의왕시", "양평": "경기도 양평군", "여주": "경기도 여주시", "동두천": "경기도 동두천시",
    "과천": "경기도 과천시", "가평": "경기도 가평군", "연천": "경기도 연천군",

    "부산 해운대": "부산광역시 해운대구", "해운대": "부산광역시 해운대구", "부산 사상": "부산광역시 사상구",
    "부산 사하": "부산광역시 사하구", "부산 동래": "부산광역시 동래구", "부산 남구": "부산광역시 남구",
    "부산 북구": "부산광역시 북구", "부산 강서": "부산광역시 강서구", "부산 기장": "부산광역시 기장군",
    "부산진구": "부산광역시 부산진구", "수영구": "부산광역시 수영구", "연제구": "부산광역시 연제구",
    "금정구": "부산광역시 금정구", "영도구": "부산광역시 영도구",

    "대구 달서": "대구광역시 달서구", "달서구": "대구광역시 달서구", "수성구": "대구광역시 수성구",
    "대구 북구": "대구광역시 북구", "대구 동구": "대구광역시 동구", "대구 서구": "대구광역시 서구",
    "대구 남구": "대구광역시 남구", "달성군": "대구광역시 달성군", "군위군": "대구광역시 군위군",

    "광주 광산": "광주광역시 광산구", "광산구": "광주광역시 광산구", "광주 북구": "광주광역시 북구",
    "광주 서구": "광주광역시 서구", "광주 남구": "광주광역시 남구", "광주 동구": "광주광역시 동구",

    "울산 남구": "울산광역시 남구", "울산 동구": "울산광역시 동구", "울산 북구": "울산광역시 북구",
    "울주": "울산광역시 울주군", "울주군": "울산광역시 울주군",

    "둔산동": "대전광역시", "둔산": "대전광역시", "성심당": "대전광역시", "은행동": "대전광역시", "으능정이": "대전광역시",
    "대전역": "대전광역시", "중앙시장": "대전광역시", "유성온천": "대전광역시", "카이스트": "대전광역시", "KAIST": "대전광역시",
    "충남대": "대전광역시", "엑스포": "대전광역시", "테크노밸리": "대전광역시", "관저동": "대전광역시", "갈마동": "대전광역시",
    "반석동": "대전광역시 유성구", "반석": "대전광역시 유성구", "노은동": "대전광역시 유성구",
    "노은1동": "대전광역시 유성구", "노은2동": "대전광역시 유성구", "노은3동": "대전광역시 유성구",
    "지족동": "대전광역시 유성구", "죽동": "대전광역시 유성구", "월평동": "대전광역시", "가양동": "대전광역시", "도마동": "대전광역시", "신탄진": "대전광역시",
    "유성구": "대전광역시 유성구", "대덕구": "대전광역시 대덕구", "대전 서구": "대전광역시 서구", "대전 중구": "대전광역시 중구", "대전 동구": "대전광역시 동구",

    "세종": "세종특별자치시", "조치원": "세종특별자치시",

    "춘천": "강원특별자치도 춘천시", "원주": "강원특별자치도 원주시", "강릉": "강원특별자치도 강릉시", "동해": "강원특별자치도 동해시",
    "태백": "강원특별자치도 태백시", "속초": "강원특별자치도 속초시", "삼척": "강원특별자치도 삼척시", "홍천": "강원특별자치도 홍천군",
    "횡성": "강원특별자치도 횡성군", "영월": "강원특별자치도 영월군", "평창": "강원특별자치도 평창군", "정선": "강원특별자치도 정선군",
    "철원": "강원특별자치도 철원군", "화천": "강원특별자치도 화천군", "양구": "강원특별자치도 양구군", "인제": "강원특별자치도 인제군",
    "고성": "강원특별자치도 고성군", "양양": "강원특별자치도 양양군",

    "청주": "충청북도 청주시", "충주": "충청북도 충주시", "제천": "충청북도 제천시", "보은": "충청북도 보은군",
    "옥천": "충청북도 옥천군", "영동": "충청북도 영동군", "증평": "충청북도 증평군", "진천": "충청북도 진천군",
    "괴산": "충청북도 괴산군", "음성": "충청북도 음성군", "단양": "충청북도 단양군",
    "천안": "충청남도 천안시", "공주": "충청남도 공주시", "보령": "충청남도 보령시", "아산": "충청남도 아산시",
    "서산": "충청남도 서산시", "논산": "충청남도 논산시", "계룡": "충청남도 계룡시", "당진": "충청남도 당진시",
    "금산": "충청남도 금산군", "부여": "충청남도 부여군", "서천": "충청남도 서천군", "청양": "충청남도 청양군",
    "홍성": "충청남도 홍성군", "예산": "충청남도 예산군", "태안": "충청남도 태안군",

    "전주": "전북특별자치도 전주시", "군산": "전북특별자치도 군산시", "익산": "전북특별자치도 익산시", "정읍": "전북특별자치도 정읍시",
    "남원": "전북특별자치도 남원시", "김제": "전북특별자치도 김제시", "완주": "전북특별자치도 완주군", "진안": "전북특별자치도 진안군",
    "무주": "전북특별자치도 무주군", "장수": "전북특별자치도 장수군", "임실": "전북특별자치도 임실군", "순창": "전북특별자치도 순창군",
    "고창": "전북특별자치도 고창군", "부안": "전북특별자치도 부안군",
    "목포": "전라남도 목포시", "여수": "전라남도 여수시", "순천": "전라남도 순천시", "나주": "전라남도 나주시",
    "광양": "전라남도 광양시", "담양": "전라남도 담양군", "곡성": "전라남도 곡성군", "구례": "전라남도 구례군",
    "고흥": "전라남도 고흥군", "보성": "전라남도 보성군", "화순": "전라남도 화순군", "장흥": "전라남도 장흥군",
    "강진": "전라남도 강진군", "해남": "전라남도 해남군", "영암": "전라남도 영암군", "무안": "전라남도 무안군",
    "함평": "전라남도 함평군", "영광": "전라남도 영광군", "장성": "전라남도 장성군", "완도": "전라남도 완도군",
    "진도": "전라남도 진도군", "신안": "전라남도 신안군",

    "포항": "경상북도 포항시", "경주": "경상북도 경주시", "김천": "경상북도 김천시", "안동": "경상북도 안동시",
    "구미": "경상북도 구미시", "영주": "경상북도 영주시", "영천": "경상북도 영천시", "상주": "경상북도 상주시",
    "문경": "경상북도 문경시", "경산": "경상북도 경산시", "의성": "경상북도 의성군", "청송": "경상북도 청송군",
    "영양": "경상북도 영양군", "영덕": "경상북도 영덕군", "청도": "경상북도 청도군", "고령": "경상북도 고령군",
    "성주": "경상북도 성주군", "칠곡": "경상북도 칠곡군", "예천": "경상북도 예천군", "봉화": "경상북도 봉화군",
    "울진": "경상북도 울진군", "울릉": "경상북도 울릉군",
    "창원": "경상남도 창원시", "진주": "경상남도 진주시", "통영": "경상남도 통영시", "사천": "경상남도 사천시",
    "김해": "경상남도 김해시", "밀양": "경상남도 밀양시", "거제": "경상남도 거제시", "양산": "경상남도 양산시",
    "의령": "경상남도 의령군", "함안": "경상남도 함안군", "창녕": "경상남도 창녕군", "남해": "경상남도 남해군",
    "하동": "경상남도 하동군", "산청": "경상남도 산청군", "함양": "경상남도 함양군", "거창": "경상남도 거창군",
    "합천": "경상남도 합천군",

    "제주": "제주특별자치도", "제주시": "제주특별자치도 제주시", "서귀포": "제주특별자치도 서귀포시"
  }
};

function matchIndustry(text) {
  const t = (text || "").toLowerCase();
  const entries = Object.entries(INDUSTRY_MATCH_TABLE.aliases)
    .sort((a, b) => b[0].length - a[0].length);
  for (const [alias, standard] of entries) {
    if (!t.includes(alias.toLowerCase())) continue;
    for (const [group, standards] of Object.entries(INDUSTRY_MATCH_TABLE.standardToGroup)) {
      if (standards.includes(standard) || standards.some(s => standard.includes(s))) {
        return { group, alias, standard, label: CONDLABEL.industry[group] };
      }
    }
  }
  for (const [group, kws] of Object.entries(INDUSTRY_MATCH_TABLE.fallbackKeywords)) {
    const hit = kws.find(k => t.includes(k.toLowerCase()));
    if (hit) return { group, alias: hit, standard: hit, label: CONDLABEL.industry[group] };
  }
  return null;
}

function matchRegion(text) {
  const t = (text || "").toLowerCase();
  const aliasEntries = Object.entries(REGION_MATCH_TABLE.aliases)
    .sort((a, b) => b[0].length - a[0].length);
  for (const [alias, standard] of aliasEntries) {
    if (!t.includes(alias.toLowerCase())) continue;
    for (const [group, names] of Object.entries(REGION_MATCH_TABLE.groups)) {
      if (names.some(n => standard.includes(n) || n.includes(standard))) {
        return { group, alias, standard, label: CONDLABEL.region[group] };
      }
    }
  }
  for (const [group, names] of Object.entries(REGION_MATCH_TABLE.groups)) {
    const hit = names.find(n => t.includes(n.toLowerCase()));
    if (hit) return { group, alias: hit, standard: hit, label: CONDLABEL.region[group] };
  }
  const anyHit = REGION_MATCH_TABLE.anyKeywords.find(k => t.includes(k.toLowerCase()));
  if (anyHit) {
    const national = ["전국", "전국구", "전지역", "전체 지역"].includes(anyHit);
    return { group: "any", alias: anyHit, standard: "전국", label: CONDLABEL.region.any, intent: national ? "national" : "unrestricted" };
  }
  return null;
}

function buildMatchingNote(answers) {
  const meta = answers && answers._matchMeta;
  const mode = regionMatchMode(answers);
  if (!meta && mode === "none") return "";
  const parts = [];
  if (meta && meta.industry) parts.push(`업종 '${meta.industry.alias}'${josa(meta.industry.alias, "은", "는")} '${meta.industry.standard}' 기준으로 ${meta.industry.label}${josa(meta.industry.label, "으로", "로")}`);
  if (meta && meta.region) parts.push(`지역 '${meta.region.alias}'${josa(meta.region.alias, "은", "는")} '${meta.region.standard}' 기준으로 ${meta.region.label}${josa(meta.region.label, "으로", "로")}`);
  const prefix = parts.length ? `${parts.join(", ")} 해석해 매칭했습니다.` : "";
  if (mode === "national_first") return `${prefix} 전국 공통 공고를 먼저, 그 다음 해당 지역 공고를 보여드립니다.`.trim();
  if (mode === "strict") return `${prefix} 지역 제한 질문으로 보고 해당 지역 공고만 보여드립니다.`.trim();
  if (mode === "national_only") return `${prefix} 전국 단위 공고만 보여드립니다.`.trim();
  return prefix;
}

function hasBatchim(text) {
  const ch = (text || "").trim().slice(-1);
  const code = ch.charCodeAt(0);
  return code >= 0xac00 && code <= 0xd7a3 && ((code - 0xac00) % 28) > 0;
}

function josa(text, withBatchim, withoutBatchim) {
  return hasBatchim(text) ? withBatchim : withoutBatchim;
}

function regionSpecificHit(p, regionMeta) {
  if (!regionMeta || !regionMeta.standard) return false;
  const tokens = new Set([regionMeta.standard, regionMeta.alias]);
  const standardParts = regionMeta.standard.split(/\s+/).filter(Boolean);
  const specificParts = standardParts.length > 1 ? standardParts.slice(1) : standardParts;
  tokens.clear();
  if (regionMeta.alias) tokens.add(regionMeta.alias);
  specificParts.forEach(part => {
    if (part.length >= 2) {
      tokens.add(part);
      const shortPart = part.replace(/(특별자치도|특별자치시|특별시|광역시|자치도|도|시|군|구)$/g, "");
      if (shortPart.length >= 2) tokens.add(shortPart);
    }
  });
  if (standardParts.length > 1) {
    const parent = standardParts[0];
    tokens.add(parent);
    const shortParent = parent.replace(/(특별자치도|특별자치시|특별시|광역시|자치도|도)$/g, "");
    if (shortParent.length >= 2) tokens.add(shortParent);
  }
  if (standardParts.length === 1) {
    const base = regionMeta.standard.replace(/(특별자치도|특별자치시|특별시|광역시|자치도|도|시|군|구)$/g, "");
    if (base.length >= 2) tokens.add(base);
  }
  const text = `${p.title || ""} ${p.org || ""} ${p.executor || ""} ${p.targetDetail || ""}`.toLowerCase();
  return [...tokens].filter(Boolean).some(tok => text.includes(tok.toLowerCase()));
}

// 자연어 → 슬롯 추출. goals는 다중 후보(goalCands)도 반환(시맨틱/되묻기용).
function parseSeed(text) {
  if (!text) return {};
  const t = text.toLowerCase();
  const out = {};
  const meta = {};
  const goalCands = [];
  for (const [g, kws] of Object.entries(GOAL_KW))
    if (kws.some(k => t.includes(k))) goalCands.push(g);
  if (goalCands.length) { out.goal = goalCands[0]; if (goalCands.length > 1) out.goalCands = goalCands; }
  const industryMatch = matchIndustry(text);
  if (industryMatch) { out.industry = industryMatch.group; meta.industry = industryMatch; }
  for (const [s, kws] of Object.entries(STAGE_KW))
    if (kws.some(k => t.includes(k))) { out.stage = s; break; }
  const regionMatch = matchRegion(text);
  if (regionMatch) { out.region = regionMatch.group; meta.region = regionMatch; }
  const specialTargets = detectUserSpecialTargets(text);
  if (specialTargets.length) meta.specialTargets = specialTargets;
  const lifecycle = detectLifecycleIntent(text);
  if (lifecycle) meta.lifecycle = lifecycle;
  if (Object.keys(meta).length) out._matchMeta = meta;
  return out;
}

/* ══════════════════════════════════════════════
   답변 생성기 (템플릿 자연어 — LLM 없이 "생성형 느낌")
   ══════════════════════════════════════════════
   composeReply(answers, text, prevTop):
   - prevTop(직전 결과 N건)이 있으면 후속질문 라우팅(쉬운/서류/마감/더)
   - 없거나 조건질의면 computeMatches 신규 검색 요약
   반환: { text, cites:[pid], count?, zero?, more? }                       */
/* ── 어휘 기반 시맨틱 검색 (2단계, 임베딩 모델 없이 브라우저에서 즉시) ──
   한글 2-gram + 단어 토큰의 겹침으로 자유질의 강건성 확보.
   추후 임베딩 cosine으로 lexicalScores를 교체하면 finalScore 구조 그대로 업그레이드. */
function tokenize(text) {
  const t = (text || "").toLowerCase().replace(/[^가-힣a-z0-9\s]/g, " ");
  const words = t.split(/\s+/).filter(w => w.length >= 2);
  const han = t.replace(/[^가-힣]/g, "");
  const grams = [];
  for (let i = 0; i < han.length - 1; i++) grams.push(han.slice(i, i + 2));
  return new Set([...words, ...grams]);
}
let _searchIndex = null;
function buildSearchIndex() {
  _searchIndex = {};
  for (const p of (window.POLICIES || [])) {
    const text = `${p.title || ""} ${p.purpose || ""} ${p.benefits || ""} ${p.targetDetail || ""}`;
    _searchIndex[p.id] = tokenize(text);
  }
}
// 쿼리 → {pid: 0~1 어휘 유사도}
function lexicalScores(query) {
  if (!_searchIndex || Object.keys(_searchIndex).length !== (window.POLICIES || []).length) buildSearchIndex();
  const qt = [...tokenize(query)];
  const out = {};
  for (const p of (window.POLICIES || [])) {
    const idx = _searchIndex[p.id];
    if (!idx || !qt.length) { out[p.id] = 0; continue; }
    let hit = 0;
    for (const tok of qt) if (idx.has(tok)) hit++;
    out[p.id] = hit / qt.length;
  }
  return out;
}
// 하이브리드: 룰 점수(pscore) + 어휘 유사도. 하드필터 통과 집합에만 적용.
function hybridRank(matched, freeText) {
  if (!freeText || !freeText.trim() || !matched.length) return matched;
  const lex = lexicalScores(freeText);
  const alpha = 0.6, beta = 0.4;
  return matched
    .map(p => ({ ...p, _final: alpha * (p.pscore / 99) + beta * (lex[p.id] || 0) }))
    .sort((a, b) => (b._final || 0) - (a._final || 0));
}

function composeReply(answers, text, prevTop) {
  const t = (text || "").toLowerCase();
  const matchNote = buildMatchingNote(answers);

  // ── 후속질문 라우팅 (직전 결과 안에서) ──
  if (prevTop && prevTop.length) {
    if (/쉬운|쉽게|간단|바로|당장|가능한|신청 가능/.test(t)) {
      const easy = prevTop.filter(p => p.eligible === "able").slice(0, 3);
      if (easy.length)
        return { text: `바로 신청 가능한 걸로 ${easy.length}건 골랐어요. 자격 조건이 명확한 사업이에요.`,
                 cites: easy.map(p => p.id) };
      return { text: "추천 사업 모두 자격을 한 번 더 확인하는 게 좋아요. 상세에서 신청 조건을 확인해 주세요.",
               cites: prevTop.slice(0, 3).map(p => p.id) };
    }
    if (/서류|준비물|구비|필요한 것|뭐가 필요|챙길/.test(t)) {
      const p = prevTop[0];
      const docs = (p.prepare || []).map(x => x.label).filter(Boolean).slice(0, 5);
      return { text: `「${p.title.slice(0, 26)}」 기준 준비물이에요: ${docs.length ? docs.join(", ") : "자세한 서류는 공고 원문을 확인해 주세요"}.`,
               cites: [p.id] };
    }
    if (/마감|언제까지|기간|급한|얼마 남/.test(t)) {
      const urgent = prevTop.filter(p => p.dday != null && p.dday >= 0).sort((a, b) => a.dday - b.dday).slice(0, 3);
      if (urgent.length)
        return { text: `마감 임박순이에요. 가장 급한 건 D-${urgent[0].dday}, 「${urgent[0].title.slice(0, 22)}」예요.`,
                 cites: urgent.map(p => p.id) };
      return { text: "추천 사업 중 상시 접수가 많아요. 마감일은 각 공고에서 확인해 주세요.",
               cites: prevTop.slice(0, 3).map(p => p.id) };
    }
    if (/더|다른|또|추가|그 외|나머지/.test(t)) return { more: true };
    if (/금액|얼마|지원금|얼마나/.test(t)) {
      const withAmt = prevTop.filter(p => window.amountVerified(p)).slice(0, 3);
      const list = (withAmt.length ? withAmt : prevTop.slice(0, 3))
        .map(p => `「${p.title.slice(0, 16)}」 ${window.amountText(p)}`).join(" · ");
      return { text: `지원 규모예요: ${list}`, cites: (withAmt.length ? withAmt : prevTop.slice(0, 3)).map(p => p.id) };
    }
  }

  // ── 조건 기반 신규 검색 요약 (prevTop이 오면 하이브리드 리랭크 결과 사용) ──
  const matches = (prevTop && prevTop.length) ? prevTop : computeMatches(answers).filter(p => p.pscore > 0);
  if (!matches.length)
    return { text: "조건에 딱 맞는 공고를 아직 못 찾았어요. 조건을 바꿔보거나 알림을 신청하면 새 공고가 뜰 때 알려드릴게요.",
             cites: [], zero: true };
  const top = matches.slice(0, 3);
  const condText = Object.entries(answers).filter(([k]) => CONDLABEL[k])
    .map(([k, v]) => CONDLABEL[k][v]).join("·");
  const regionFollowup = (!answers.region && (answers.goal || answers.industry))
    ? " 사업장이 어느 지역인가요? 지역을 알려주시면 전국 공통 공고 다음에 해당 지역 공고만 좁혀드릴게요."
    : "";
  return {
    text: `${matchNote ? matchNote + " " : ""}${condText ? condText + " 조건으로 " : ""}맞는 사업 ${matches.length}건을 찾았어요. 가장 잘 맞는 건 「${top[0].title.slice(0, 24)}」 — ${top[0].purpose}${regionFollowup}`,
    cites: top.map(p => p.id), count: matches.length,
  };
}

/** 숫자 포맷 */
const krw = n => (n || 0).toLocaleString("ko-KR");

/* ════════════════════════════════════════════════════════════════
   생성형 해설 (3단계) — 저장된 Gemini 키로 룰베이스 답변을 자연어로 보강.
   환각방지 원칙:
   - cites(하드필터 결과)는 절대 바꾸지 않음. Gemini는 "설명"만 다시 씀.
   - 인용된 정책의 DB 필드만 컨텍스트로 제공(grounding 강제).
   - 키 없음/오류/타임아웃 → 호출자가 룰베이스 텍스트 유지(graceful).
   상권챗봇과 동일 키(gemini_api_key)·모델(gemini-2.5-flash) 규약.
   ════════════════════════════════════════════════════════════════ */
function geminiKey() {
  try { return (localStorage.getItem("gemini_api_key") || "").trim(); } catch (e) { return ""; }
}
function geminiEnabled() { return !!geminiKey(); }

// 인용 정책만 근거로 한 그라운딩 프롬프트 (없는 정보 생성 금지)
function buildGroundingPrompt(userText, policies, baseAnswer) {
  const ctx = (policies || []).slice(0, 3).map((p, i) => {
    const amt = (window.amountText ? window.amountText(p) : "") || p.amountPerApplicant || p.amountLabel || "공고 확인";
    return `${i + 1}. ${p.title}\n   - 목적: ${p.purpose || "-"}\n   - 지원규모: ${amt}\n   - 대상: ${p.targetDetail || "-"}\n   - 기간: ${p.period || "상시/공고 확인"}`;
  }).join("\n");
  return [
    "당신은 소상공인 정책을 쉽게 안내하는 한국어 도우미입니다.",
    "아래 [검색된 정책]만을 근거로, 사용자 질문에 토스처럼 친근한 존댓말로 2~3문장 답하세요.",
    "",
    "규칙(반드시 지킬 것):",
    "- [검색된 정책]에 없는 정책·금액·조건·날짜를 절대 지어내지 마세요.",
    "- 금액은 제공된 표기를 그대로 쓰세요(임의 계산·반올림 금지).",
    "- 정책명을 1~2개 자연스럽게 언급하되 나열식이 아닌 대화체로.",
    "- 불확실하면 '공고 원문에서 확인하세요'라고 안내.",
    "- 2~3문장, 이모지는 최대 1개, 마크다운/목록 쓰지 마세요.",
    "",
    `[사용자 질문]\n${userText || "내게 맞는 지원사업 추천"}`,
    "",
    `[검색된 정책]\n${ctx || "(없음)"}`,
    "",
    `[기존 요약(어조 참고용, 사실은 위 정책에서만)]\n${baseAnswer || ""}`,
  ].join("\n");
}

// Gemini 호출 — 성공 시 텍스트, 실패/타임아웃 시 null
async function callGemini(prompt, opts) {
  const key = geminiKey();
  if (!key) return null;
  const model = (opts && opts.model) || "gemini-2.5-flash";
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), (opts && opts.timeoutMs) || 9000);
  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(key)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl.signal,
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { temperature: 0.5, maxOutputTokens: (opts && opts.maxOutputTokens) || 256 },
        }),
      }
    );
    clearTimeout(to);
    if (!res.ok) return null;
    const data = await res.json();
    const text = data?.candidates?.[0]?.content?.parts?.map(p => p.text).join("").trim();
    return text && text.length >= 6 ? text : null;
  } catch (e) { clearTimeout(to); return null; }
}

// 룰베이스 답변을 Gemini로 보강 — cites는 호출자가 그대로 유지
async function enhanceReply(userText, citedPolicies, baseAnswer) {
  if (!geminiEnabled() || !citedPolicies || !citedPolicies.length) return null;
  return await callGemini(buildGroundingPrompt(userText, citedPolicies, baseAnswer));
}

// 정책 상세 — 단일 정책만 근거로 "쉬운 설명" 생성. id별 sessionStorage 캐시(할당량 절약).
async function explainPolicy(p) {
  if (!geminiEnabled() || !p) return null;
  const ck = "pf_ai_explain_" + p.id;
  try { const c = sessionStorage.getItem(ck); if (c) return c; } catch (e) {}
  const amt = (window.amountText ? window.amountText(p) : "") || p.amountPerApplicant || p.amountLabel || "공고 확인";
  const prompt = [
    "아래 [정책]을 소상공인이 이해하기 쉽게 한국어로 풀어 설명하세요.",
    "규칙(반드시): 제공된 정보 밖의 내용·숫자·날짜를 지어내지 마세요. 금액은 표기 그대로(임의 계산 금지). 3~4문장, 존댓말, 마크다운/목록 금지, 이모지 최대 1개.",
    "초점: ① 이 사업이 한마디로 무엇인지 ② 누구에게 특히 유리한지 ③ 무엇을 받을 수 있는지.",
    "",
    `[정책]\n제목: ${p.title}\n목적: ${p.purpose || "-"}\n대상: ${p.targetDetail || "-"}\n지원내용: ${p.benefits || "-"}\n지원금액: ${amt}\n신청기간: ${p.period || "상시/공고 확인"}`,
  ].join("\n");
  const out = await callGemini(prompt, { timeoutMs: 12000, maxOutputTokens: 320 });
  if (out) { try { sessionStorage.setItem(ck, out); } catch (e) {} }
  return out;
}

/* ── Export to window ── */
Object.assign(window, {
  geminiKey, geminiEnabled, buildGroundingPrompt, callGemini, enhanceReply, explainPolicy,
  USER_TYPES, TYPE_PROFILE, QUESTIONS, CONDLABEL, CAT_ICON, INDUSTRY_MATCH_TABLE, REGION_MATCH_TABLE,
  computeDday, questionsForType, computeMatches, optionCount, parseSeed, composeReply, krw,
  lexicalScores, hybridRank, tokenize, matchIndustry, matchRegion, buildMatchingNote, regionSpecificHit,
  regionMatchMode, comparePolicyMatches, policyRegionHints, policySpecificRegionIds, policyRegionCompatible,
  policySpecialTargets, specialTargetAllowed, detectLifecycleIntent, policyLifecycleTargets, lifecycleAllowed,
});
