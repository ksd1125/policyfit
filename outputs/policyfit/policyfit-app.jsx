/**
 * policyfit-app.jsx
 * ─────────────────────────────────────────────
 * 화면 컴포넌트 + App 라우팅
 * P1 디자인 시스템 (CSS), P2 온보딩, P3 진단,
 * P4 결과, P5 부가, P6 전문가/관리자, P7 상세
 */
const { useState, useEffect, useRef } = React;

const SUGGESTS = ["운영자금이 필요해요", "온라인 판매를 하고 싶어요", "창업을 준비 중이에요"];

// amountVerified / amountText 는 policyfit-config.js에서 window에 등록 (모듈 격리 우회 — window. 직접 호출)

/* ══════════════════════════════════════════════
   P2  HOME (온보딩 + 히어로)
   ══════════════════════════════════════════════ */
function Home({ onStart, onPickType, onOpenPolicy, onBrowse }) {
  const [q, setQ] = useState("");
  const trending = [...POLICIES]
    .filter(p => p.dday != null && p.dday >= 0)
    .sort((a, b) => a.dday - b.dday)
    .slice(0, 3);

  return (
    <div className="page rise">
      <section className="hero">
        <div className="eyebrow"><Icon name="spark" size={15} />AI 정책 도우미</div>
        <h1>복잡한 공고문은 그만.<br /><span className="hl">대화 한 번</span>으로 내 정책을 찾으세요.</h1>
        <p className="sub">목적·금액·기간·준비물까지 핵심만 정리해 드려요. 검색이 아니라, 몇 가지 질문에 답하면 나에게 딱 맞는 지원사업이 골라집니다.</p>

        <div className="askbar">
          <Icon name="spark" size={22} stroke={2.2} style={{ color: "var(--accent)" }} />
          <input value={q} onChange={e => setQ(e.target.value)}
            placeholder="무엇을 도와드릴까요? 예: 운영자금이 필요해요"
            onKeyDown={e => e.key === "Enter" && onStart(q)} />
          <button className="go" onClick={() => onStart(q)}><Icon name="arrow-right" size={22} /></button>
        </div>

        <div className="suggests">
          {SUGGESTS.map(s => <button key={s} className="suggest-pill" onClick={() => onStart(s)}>{s}</button>)}
        </div>

        <div className="hero-types">
          <span className="hero-types-lbl">내 상황에 맞게 시작하기</span>
          <div className="type-pills">
            {USER_TYPES.map(u =>
              <button key={u.id} className="type-pill" onClick={() => onPickType(u.id)}>
                <Icon name={u.icon} size={17} />{u.label}
              </button>
            )}
          </div>
        </div>
      </section>

      {trending.length > 0 && (
        <section className="sec">
          <div className="sec-head">
            <h2>마감이 임박한 사업</h2>
            <button className="more" onClick={onBrowse}>전체 보기<Icon name="arrow-right" size={15} /></button>
          </div>
          <div className="trend-row">
            {trending.map(p => <PolicyCard key={p.id} p={p} compact onClick={() => onOpenPolicy(p)} />)}
          </div>
        </section>
      )}

      {/* P5 "왜 정책핏?" */}
      <section className="why">
        <div className="why-head"><h2>왜 정책핏인가요?</h2><p>기존 정책 포털과 무엇이 다른지 한눈에 보세요.</p></div>
        <div className="why-grid">
          <div className="why-item"><div className="ic"><Icon name="target" size={22} /></div><h4>검색이 아닌 진단</h4><p>업종·단계·목적 몇 가지만 답하면 나에게 맞는 사업만 골라줘요.</p><span className="vs">기존 포털: 키워드 검색 → 수백 건 목록</span></div>
          <div className="why-item"><div className="ic"><Icon name="doc" size={22} /></div><h4>공고문 대신 핵심 카드</h4><p>목적·지원금액·기간·내가 준비할 것만 한눈에.</p><span className="vs">기존 포털: 수십 페이지 PDF 공고문</span></div>
          <div className="why-item"><div className="ic"><Icon name="headset" size={22} /></div><h4>상담·정책 담당자도 함께</h4><p>상담 현황 브리핑과 사업 비교까지, 담당자를 위한 도구도 한곳에.</p><span className="vs">기존 포털: 담당자가 직접 공고 대조</span></div>
        </div>
      </section>

      <footer className="home-foot">
        <div className="home-foot-brand"><span className="logo-mark"><Icon name="spark" size={15} stroke={2.4} /></span>정책핏</div>
        <p>본 화면의 정책 정보는 서비스 시연을 위한 예시 데이터입니다. 실제 신청 전 각 기관의 공고를 확인하세요.</p>
        <p>문의 · 소상공인 통합콜센터 1357</p>
      </footer>
    </div>
  );
}

/* ══════════════════════════════════════════════
   P3  DIAGNOSE (진단 챗봇)
   ══════════════════════════════════════════════ */
function Diagnose({ userType, seed, prefill, questions, onComplete, onBack }) {
  const QSET = questions || QUESTIONS;
  const askList = QSET.filter(q => !(prefill && prefill[q.id]));
  const [msgs, setMsgs] = useState([]);
  const [answers, setAnswers] = useState(prefill || {});
  const [step, setStep] = useState(0);
  const [typing, setTyping] = useState(false);
  const [done, setDone] = useState(false);
  const [chatQ, setChatQ] = useState("");   // 멀티턴 자유 입력
  const [moreOffset, setMoreOffset] = useState(3);

  const utLabel = (USER_TYPES.find(u => u.id === userType) || {}).label;
  const typeNote = (TYPE_PROFILE[userType] || {}).note;
  const scrollDown = () => requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }));

  function finish(ans) {
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      const found = computeMatches(ans).length;
      const text = found > 0
        ? `조건에 맞는 지원사업 ${found}건을 매칭도 순으로 정리했어요.`
        : "딱 맞는 공고는 아직 없지만, 비슷한 사업과 알림 신청을 안내해 드릴게요.";
      setMsgs(m => [...m, { type: "ai", text }, { type: "result", count: found, answers: ans }]);
      setDone(true); scrollDown();
    }, 950);
  }

  // 멀티턴 자유 입력 — 조건 변경(재검색) 또는 후속질문(라우팅)
  function handleChat(text) {
    if (!text.trim()) return;
    setMsgs(m => [...m, { type: "chatme", text }]);
    setChatQ("");
    const seed = parseSeed(text);
    const hasNew = ["goal", "stage", "region", "industry"].some(k => seed[k] && seed[k] !== answers[k]);
    const merged = hasNew ? { ...answers, ...seed } : answers;
    if (hasNew) { setAnswers(merged); setMoreOffset(3); }
    setTyping(true); scrollDown();
    setTimeout(() => {
      setTyping(false);
      let aiMsg;
      if (!hasNew && /더|다른|또|추가|나머지/.test(text)) {
        const all = computeMatches(merged).filter(p => p.pscore > 0);
        const next = all.slice(moreOffset, moreOffset + 3);
        setMoreOffset(o => o + 3);
        aiMsg = { type: "chatai", text: next.length ? `${next.length}건 더 보여드릴게요.` : "더 보여드릴 사업이 없어요. 조건을 바꿔보세요.", cites: next.map(p => p.id) };
      } else {
        // 2단계: 원본 자유 텍스트로 어휘 하이브리드 리랭크 (하드필터 통과 집합에만)
        const ranked = hybridRank(computeMatches(merged).filter(p => p.pscore > 0), text);
        const isFollowUp = !hasNew && /쉬운|쉽게|간단|바로|당장|가능|서류|준비물|구비|필요한|마감|언제|기간|급한|더|다른|또|추가|나머지|금액|얼마|지원금/.test(text);
        const r = composeReply(merged, isFollowUp ? text : "", ranked);
        const enable = window.geminiEnabled && window.geminiEnabled() && (r.cites && r.cites.length) && !r.zero;
        const msgId = "g" + Date.now() + Math.random().toString(36).slice(2, 6);
        aiMsg = { type: "chatai", id: msgId, text: r.text, cites: r.cites || [], zero: r.zero, ans: merged, gen: enable ? "pending" : null };
        // 키가 있으면: 인용된 정책만 근거로 자연어 보강 (cites는 불변, 실패 시 룰베이스 유지)
        if (enable) {
          const cited = (r.cites || []).map(pid => (window.POLICIES || []).find(p => p.id === pid)).filter(Boolean);
          window.enhanceReply(text, cited, r.text).then(out => {
            setMsgs(ms => ms.map(mm => mm.id === msgId
              ? (out ? { ...mm, text: out, gen: "done" } : { ...mm, gen: null })
              : mm));
            scrollDown();
          });
        }
      }
      setMsgs(m => [...m, aiMsg]);
      setDone(true); scrollDown();
    }, 700);
  }

  useEffect(() => {
    const known = [];
    if (prefill?.goal) known.push("목적");
    if (prefill?.industry) known.push("업종");
    let greet;
    if (seed && known.length) greet = `"${seed}" 잘 이해했어요. ${known.join("·")}은 파악했고, ${askList.length}가지만 더 확인할게요.`;
    else if (userType) greet = `${utLabel}이시군요! ${typeNote || ""} ${askList.length ? `${askList.length}가지만 답하면 딱 맞는 사업을 골라드려요.` : ""}`;
    else if (seed) greet = `"${seed}" 관련해서 도와드릴게요. 가장 급한 것부터 골라주세요.`;
    else greet = "안녕하세요! 가장 급한 것 하나만 골라도 결과를 볼 수 있어요.";
    setMsgs([{ type: "ai", text: greet }]);
    setTyping(true);
    const t = setTimeout(() => {
      setTyping(false);
      if (askList.length === 0) finish(answers);
      else { setMsgs(m => [...m, { type: "q", q: askList[0] }]); scrollDown(); }
    }, 800);
    return () => clearTimeout(t);
  }, []);

  function advance(ans, label, skipped) {
    if (label) setMsgs(m => [...m, { type: "me", text: label }]);
    else if (skipped) setMsgs(m => [...m, { type: "skip" }]);
    setAnswers(ans);
    const ns = step + 1; setStep(ns); scrollDown(); setTyping(true);
    setTimeout(() => {
      setTyping(false);
      if (ns < askList.length) { setMsgs(m => [...m, { type: "q", q: askList[ns] }]); scrollDown(); }
      else finish(ans);
    }, 700);
  }

  const pick = (qid, opt) => advance({ ...answers, [qid]: opt.id }, opt.label, false);
  const skip = () => advance(answers, null, true);
  const liveCount = computeMatches(answers).length;
  const optional = qid => qid === "industry" || qid === "region";
  const lastQIdx = (() => { for (let i = msgs.length - 1; i >= 0; i--) if (msgs[i].type === "q") return i; return -1; })();
  const answered = Object.keys(answers).length;

  return (
    <div className="page">
      <div className="col chat-wrap">
        <div className="chat-progress">
          <button className="btn btn-sm btn-ghost" onClick={onBack} style={{ padding: "8px 10px" }}><Icon name="arrow-left" size={18} /></button>
          <div className="bar"><i style={{ width: `${done ? 100 : (step / Math.max(askList.length, 1)) * 100}%` }} /></div>
          {!done && (msgs.length > 1 || typing) && (
            <button className="quickresult" onClick={() => onComplete(answers)}>
              {answered >= 1 ? `결과 ${liveCount}건 보기` : "건너뛰고 전체 보기"}<Icon name="arrow-right" size={15} />
            </button>
          )}
        </div>

        {msgs.map((m, i) => {
          if (m.type === "ai") return <div className="bubble-row fade" key={i}><Avatar /><div className="bubble ai">{m.text}</div></div>;
          if (m.type === "me") return <div className="bubble-row me fade" key={i}><div className="bubble me">{m.text}</div></div>;
          if (m.type === "skip") return <div className="skip-note fade" key={i}>이 질문은 건너뛰었어요</div>;
          if (m.type === "q") {
            const isCurrent = i === lastQIdx && !typing && !done;
            return (
              <div key={i} className="fade">
                <div className="bubble-row"><Avatar /><div className="bubble ai" style={{ maxWidth: "92%" }}><p className="q">{m.q.q}</p><p className="qh">{m.q.hint}</p></div></div>
                {isCurrent && (
                  <div className="opts">
                    {m.q.options.map(o => <Chip key={o.id} onClick={() => pick(m.q.id, o)} count={optionCount(answers, m.q.id, o.id)}>{o.label}</Chip>)}
                    {optional(m.q.id) && <button className="chip chip-skip" onClick={skip}>건너뛰기</button>}
                  </div>
                )}
              </div>
            );
          }
          if (m.type === "result") return (
            <div className="bubble-row fade" key={i} style={{ marginLeft: 48 }}>
              <button className={`btn btn-lg ${m.count ? "btn-primary" : "btn-line"}`} onClick={() => onComplete(m.answers)}>
                {m.count ? `맞춤 정책 ${m.count}건 보기` : "비슷한 사업·알림 보기"} <Icon name="arrow-right" size={20} />
              </button>
            </div>
          );
          if (m.type === "chatme") return <div className="bubble-row me fade" key={i}><div className="bubble me">{m.text}</div></div>;
          if (m.type === "chatai") return (
            <div className="fade" key={i}>
              <div className="bubble-row"><Avatar /><div className="bubble ai" style={{ maxWidth: "92%" }}>
                {m.text}
                {m.gen === "pending" && <span style={{ marginLeft: 6, fontSize: 12, color: "var(--muted)" }}>✨ 다듬는 중…</span>}
                {m.gen === "done" && <span style={{ display: "block", marginTop: 6, fontSize: 11, color: "var(--accent)" }}>✨ AI 생성 · 출처는 아래 카드에서 확인</span>}
              </div></div>
              {m.cites && m.cites.length > 0 && (
                <div className="cite-list">
                  {m.cites.map(pid => {
                    const p = (window.POLICIES || []).find(x => x.id === pid);
                    if (!p) return null;
                    return (
                      <button key={pid} className="cite-card" onClick={() => onComplete(m.ans || answers)}>
                        <span className="cite-cat">{p.category}</span>
                        <span className="cite-title">{p.title}</span>
                        <span className="cite-amt">{p.amountPerApplicant || p.amountLabel}</span>
                      </button>
                    );
                  })}
                </div>
              )}
              {m.zero && <div style={{ marginLeft: 48, marginTop: 8 }}><AlertCard answers={m.ans || answers} /></div>}
            </div>
          );
          return null;
        })}
        {typing && <div className="bubble-row fade"><Avatar /><div className="bubble ai" style={{ padding: 0 }}><div className="typing"><i /><i /><i /></div></div></div>}
      </div>

      {/* 빠른 후속질문 칩 — 타이핑 없이 클릭으로 대화 지속 */}
      {done && (
        <div className="quick-follow">
          {["신청 쉬운 건?", "서류 뭐 필요해?", "마감 임박순", "더 보여줘"].map(qf => (
            <button key={qf} className="qf-chip" onClick={() => handleChat(qf)}>{qf}</button>
          ))}
        </div>
      )}

      {/* 멀티턴 자유 입력바 — 옵션 칩과 병행, 결과 후 후속 대화 */}
      {msgs.length > 0 && (
        <div className="chat-inputbar">
          <input
            value={chatQ} onChange={e => setChatQ(e.target.value)}
            placeholder={done ? "더 물어보세요 · 예: 이 중 신청 쉬운 건?" : "또는 자유롭게 입력 · 예: 서울 음식점 운영자금"}
            onKeyDown={e => e.key === "Enter" && handleChat(chatQ)} />
          <button className="go" onClick={() => handleChat(chatQ)} aria-label="전송"><Icon name="arrow-right" size={20} /></button>
        </div>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════
   P5  ALERT CARD (조건 저장 / 알림)
   ══════════════════════════════════════════════ */
function AlertCard({ answers }) {
  const [on, setOn] = useState(false);
  const condText = Object.entries(answers).filter(([k]) => CONDLABEL[k]).map(([k, v]) => CONDLABEL[k][v]).join(" · ") || "내 조건";
  return (
    <div className={`alert-card${on ? " done" : ""}`}>
      <div className="ic"><Icon name={on ? "check-circle" : "bell"} size={22} /></div>
      <div className="alert-txt">
        <h4>{on ? "알림을 신청했어요" : "찾는 공고가 없나요?"}</h4>
        <p>{on ? `'${condText}' 조건에 맞는 새 공고가 등록되면 알려드려요.` : "조건에 맞는 새 공고가 등록되면 가장 먼저 알려드릴게요."}</p>
      </div>
      {!on && <Btn variant="primary" icon="bell" onClick={() => { localStorage.setItem("pf_alert", JSON.stringify(answers)); setOn(true); }}>새 공고 알림 받기</Btn>}
    </div>
  );
}

/* ══════════════════════════════════════════════
   P5  BROWSE (전체 둘러보기)
   ══════════════════════════════════════════════ */
function BrowseView({ onOpenPolicy, onDiagnose }) {
  const [cat, setCat] = useState(null);
  const [sort, setSort] = useState("dday");
  const byCat = {};
  POLICIES.forEach(p => { (byCat[p.category] = byCat[p.category] || []).push(p); });
  const cats = Object.entries(byCat).map(([c, items]) => ({ c, items })).sort((a, b) => b.items.length - a.items.length);

  let list = cat ? [...byCat[cat]] : [];
  if (sort === "dday") list.sort((a, b) => (a.dday ?? 9999) - (b.dday ?? 9999));
  if (sort === "amount") list.sort((a, b) => (b.amountValue ?? 0) - (a.amountValue ?? 0));

  if (!cat) {
    return (
      <div className="page rise"><div className="col" style={{ maxWidth: 920 }}>
        <div className="results-head">
          <h1>전체 지원사업 <span className="n">{POLICIES.length}건</span></h1>
          <p>유형을 선택하면 해당 분야의 사업만 모아서 볼 수 있어요.</p>
          <div className="browse-cta"><div><Icon name="target" size={18} /><span>나에게 맞는 사업만 빠르게 찾고 싶다면?</span></div>
            <Btn variant="primary" size="sm" icon="spark" onClick={onDiagnose}>맞춤 진단 시작</Btn></div>
        </div>
        <div className="cat-grid">
          {cats.map(({ c, items }) => {
            const urgent = items.filter(p => p.dday != null && p.dday >= 0 && p.dday <= 14).length;
            return (
              <button key={c} className="cat-card" onClick={() => { setCat(c); setSort("dday"); window.scrollTo({ top: 0 }); }}>
                <div className="cat-ic"><Icon name={CAT_ICON[c] || "doc"} size={24} /></div>
                <div className="cat-meta"><h3>{c}</h3><span className="cat-orgs">{new Set(items.map(p => p.org)).size}개 기관</span></div>
                <div className="cat-count"><b>{items.length}</b><span>건</span></div>
                {urgent > 0 && <span className="cat-urgent">마감임박 {urgent}</span>}
              </button>
            );
          })}
        </div>
      </div></div>
    );
  }

  return (
    <div className="page rise"><div className="col" style={{ maxWidth: 920 }}>
      <div className="results-head">
        <button className="browse-back" onClick={() => { setCat(null); window.scrollTo({ top: 0 }); }}><Icon name="arrow-left" size={16} />전체 유형</button>
        <h1 style={{ marginTop: 12 }}><span className="cat-ic-sm"><Icon name={CAT_ICON[cat] || "doc"} size={20} /></span>{cat} <span className="n">{list.length}건</span></h1>
      </div>
      <div className="results-toolbar">
        <span className="count">총 {list.length}건</span>
        <div className="sortsel">
          <button className={sort === "dday" ? "on" : ""} onClick={() => setSort("dday")}>마감임박순</button>
          <button className={sort === "amount" ? "on" : ""} onClick={() => setSort("amount")}>지원규모순</button>
        </div>
      </div>
      <div className="results-list">{list.map(p => <PolicyCard key={p.id} p={p} onClick={() => onOpenPolicy(p)} />)}</div>
    </div></div>
  );
}

/* ══════════════════════════════════════════════
   P4  RESULTS (결과 화면)
   ══════════════════════════════════════════════ */
function groupPolicyResults(list, answers) {
  const mode = regionMatchMode(answers);
  const meta = answers && answers._matchMeta;
  const regionName = meta && meta.region ? meta.region.standard : CONDLABEL.region[answers.region];
  if (mode === "region_first") {
    const national = list.filter(p => p._regionClass === "national");
    const regional = list.filter(p => p._regionClass === "regional");
    return [
      regional.length && {
        key: "regional",
        title: `${regionName || "내 지역"} 공고`,
        desc: "입력한 지역과 실제로 연결되는 공고를 먼저 보여드립니다.",
        items: regional,
      },
      national.length && {
        key: "national",
        title: "전국 공통 추천",
        desc: "지역 제한 없이 누구나 신청할 수 있는 전국 단위 공고입니다.",
        items: national,
      },
    ].filter(Boolean);
  }
  if (mode === "strict") {
    return [{
      key: "regional-only",
      title: `${regionName || "지역"} 공고`,
      desc: "지역만 지정한 질문이라 전국 공통 공고는 제외했습니다.",
      items: list,
    }];
  }
  if (mode === "national_only") {
    return [{
      key: "national-only",
      title: "전국 단위 공고",
      desc: "전국으로 제한한 질문이라 지역 전용 공고는 제외했습니다.",
      items: list,
    }];
  }
  if (mode === "none" && (answers.goal || answers.industry || answers.stage)) {
    const national = list.filter(p => p._regionClass === "national");
    const regional = list.filter(p => p._regionClass === "regional");
    return [
      national.length && {
        key: "national",
        title: "전국 공통 추천",
        desc: "지역을 아직 모르는 상태라 전국 단위 공고를 먼저 보여드립니다.",
        items: national,
      },
      regional.length && {
        key: "regional",
        title: "지역 공고 전체",
        desc: "사업장 지역을 알려주면 이 목록을 해당 지역 공고로 좁힐 수 있습니다.",
        items: regional,
      },
    ].filter(Boolean);
  }
  return [{ key: "all", title: "추천 공고", desc: "", items: list }];
}

function PolicyResultSection({ section, onOpenPolicy }) {
  return (
    <section className="policy-section">
      <div className="policy-section-head">
        <div>
          <h2>{section.title} <span>{section.items.length}건</span></h2>
          {section.desc && <p>{section.desc}</p>}
        </div>
      </div>
      <div className="results-list">
        {section.items.map(p => <PolicyCard key={p.id} p={p} showMatch onClick={() => onOpenPolicy(p)} />)}
      </div>
    </section>
  );
}

function Results({ answers, query, onOpenPolicy, onRedo, onDiagnose }) {
  const conds = Object.entries(answers || {}).filter(([k, v]) => CONDLABEL[k] && v);
  const hasConditions = conds.length > 0;
  const matchNote = buildMatchingNote(answers);
  const [sort, setSort] = useState(hasConditions ? "match" : "dday");

  let list = hasConditions ? computeMatches(answers) : [...POLICIES];
  // 자유질의면 어휘 관련도(2-gram)를 결합해 _final 부여 — '카페' 같은 질의가 랭킹에 반영됨
  const lexical = !!(query && query.trim() && hasConditions);
  if (lexical) list = hybridRank(list, query);
  const empty = hasConditions && list.length === 0;
  // goal을 답했을 때만 "조건 완화" 추천 (goal 미응답 시 임의 결과 방지)
  const relaxed = answers.goal
    ? computeMatches({ goal: answers.goal }).filter(p => !list.find(x => x.id === p.id)).slice(0, 4)
    : [];

  // 자유질의: 관련도(_final) 우선 정렬. 구조화 진단: 기존 매칭 정렬.
  if (sort === "match" && hasConditions) list = lexical
    ? [...list].sort((a, b) => (b._final || 0) - (a._final || 0))
    : [...list].sort(comparePolicyMatches);
  if (sort === "dday") list = [...list].sort((a, b) => (a.dday ?? 9999) - (b.dday ?? 9999));
  if (sort === "amount") list = [...list].sort((a, b) => (b.amountValue ?? 0) - (a.amountValue ?? 0));
  const sections = groupPolicyResults(list, answers);

  const condChips = (
    <div className="cond-bar">
      {conds.map(([k, v]) => <span className="cond" key={k}><span className="k">{({ industry: "업종", stage: "단계", goal: "목적", region: "지역" })[k]}</span>{CONDLABEL[k][v]}</span>)}
      <button className="btn btn-sm btn-soft" onClick={onRedo}><Icon name="filter" size={15} />조건 다시 진단</button>
    </div>
  );
  const matchNoteBlock = matchNote && (
    <p className="match-note"><Icon name="target" size={14} />{matchNote}</p>
  );

  if (!hasConditions) return <BrowseView onOpenPolicy={onOpenPolicy} onDiagnose={onDiagnose} />;

  if (empty) return (
    <div className="page rise"><div className="col" style={{ maxWidth: 760 }}>
      <div className="results-head">{condChips}</div>
      {matchNoteBlock}
      <div className="empty-big">
        <div className="ic"><Icon name="compass" size={30} /></div>
        <h1>조건에 딱 맞는 공고가 아직 없어요</h1>
        <p>지금은 해당 조건의 모집 공고가 없지만, 막다른 길이 아니에요.</p>
      </div>
      <AlertCard answers={answers} />
      {relaxed.length > 0 && <div style={{ marginTop: 28 }}>
        <div className="sec-head" style={{ marginBottom: 14 }}><h2 style={{ fontSize: 20 }}>조건을 넓힌 비슷한 사업</h2></div>
        <div className="results-list">{relaxed.map(p => <PolicyCard key={p.id} p={p} showMatch onClick={() => onOpenPolicy(p)} />)}</div>
      </div>}
      <div className="empty-actions"><Btn variant="line" full icon="filter" onClick={onRedo}>조건 바꿔서 다시 찾기</Btn></div>
    </div></div>
  );

  return (
    <div className="page rise"><div className="col" style={{ maxWidth: 920 }}>
      <div className="results-head">
        <h1><span className="n">{list.length}건</span>의 맞춤 정책을 찾았어요</h1>
        <p>입력하신 조건과 잘 맞는 순서로 정리했어요. <b>매칭도</b>는 조건과 얼마나 맞는지를 0~100으로 나타낸 점수예요.</p>
        {matchNoteBlock}
        {condChips}
      </div>
      <div className="results-toolbar">
        <span className="count">총 {list.length}건</span>
        <div className="sortsel">
          <button className={sort === "match" ? "on" : ""} onClick={() => setSort("match")}>매칭도순</button>
          <button className={sort === "dday" ? "on" : ""} onClick={() => setSort("dday")}>마감임박순</button>
          <button className={sort === "amount" ? "on" : ""} onClick={() => setSort("amount")}>지원규모순</button>
        </div>
      </div>
      <div className="policy-sections">
        {sections.map(section => <PolicyResultSection key={section.key} section={section} onOpenPolicy={onOpenPolicy} />)}
      </div>
      <AlertCard answers={answers} />
      <div className="disclaimer">본 화면의 정책 정보는 서비스 시연을 위한 예시 데이터입니다. 실제 신청 전 각 기관의 공고를 반드시 확인하세요. 문의: 소상공인 통합콜센터 1357</div>
    </div></div>
  );
}

/* ══════════════════════════════════════════════
   P7  DETAIL SHEET
   ══════════════════════════════════════════════ */
function Detail({ p, onClose }) {
  const [saved, setSaved] = useState(false);
  const haveN = p.prepare.filter(x => x.status === "have").length;
  // 생성형 "쉬운 설명" — 키 있을 때만, 이 정책 하나만 근거로 (실패/무키 시 미표시)
  const [aiText, setAiText] = useState(null);
  const [aiState, setAiState] = useState(window.geminiEnabled && window.geminiEnabled() ? "pending" : "off");
  useEffect(() => {
    let alive = true;
    if (!(window.geminiEnabled && window.geminiEnabled())) { setAiState("off"); return; }
    setAiState("pending");
    window.explainPolicy(p).then(out => {
      if (!alive) return;
      if (out) { setAiText(out); setAiState("done"); } else setAiState("off");
    });
    return () => { alive = false; };
  }, [p.id]);
  // ESC 닫기 + 배경 스크롤 잠금
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="sheet" role="dialog" aria-modal="true" aria-label="정책 상세">
        <div className="sheet-bar">
          <button className="close" onClick={onClose} aria-label="닫기"><Icon name="x" size={20} /></button>
          <span className="t">정책 상세</span>
          <span style={{ flex: 1 }} />
          <button className={`close savebtn${saved ? " on" : ""}`} onClick={() => setSaved(v => !v)} title={saved ? "저장됨" : "저장하기"}>
            <Icon name="bookmark" size={20} />{saved && <span className="save-toast">저장됨</span>}
          </button>
        </div>
        <div className="sheet-body">
          <span className="dt-cat"><Icon name={CAT_ICON[p.category] || "doc"} size={15} />{p.category}</span>
          <h1 className="dt-title">{p.title}</h1>
          <div className="dt-org"><Icon name="building" size={14} />{p.org}{p.executor && p.executor !== p.org && ` (${p.executor})`}</div>
          <div className="dt-badges">
            <EligibleBadge status={p.eligible} />
            <DdayPill dday={p.dday} />
            {p.pscore != null && <span className="elig" style={{ background: "var(--accent-soft)", color: "var(--accent-ink)" }}><Icon name="spark" size={14} />매칭도 {p.pscore}</span>}
          </div>
          <p className="block body" style={{ fontSize: 16.5, color: "var(--ink)", fontWeight: 600, margin: "4px 0 18px" }}>{p.purpose || p.summary}</p>
          <div className="stat-grid">
            <div className="stat"><div className="k"><Icon name="won" size={15} />지원 금액{(["explicit_llm", "calculated_llm", "total_only_llm"].includes(p.amountSource) && !/공고 확인|확인 필요|규모 확인/.test(p.amountPerApplicant || p.amountLabel || "")) && <span className="amt-trust" title="공고 원문에서 AI가 확인한 금액"><Icon name="check" size={10} stroke={3} />확인</span>}</div><div className="v">{p.amountPerApplicant || p.amountLabel}</div>{(p.amountSource && p.amountSource.startsWith("calculated") && p.amountTotal && p.amountTargetCount) ? (<div className="vs">총 {p.amountTotal} ÷ 대상 {p.amountTargetCount}</div>) : (p.amountSource && p.amountSource.startsWith("total_only") && p.amountTotal) ? (<div className="vs">총사업비 {p.amountTotal} · 1인 한도는 공고 확인</div>) : (p.amountSub && <div className="vs">{p.amountSub}</div>)}</div>
            <div className="stat"><div className="k"><Icon name="calendar" size={15} />신청 기간</div><div className="v">{p.dday != null ? (p.dday >= 0 ? `D-${p.dday}` : "마감") : "상시"}</div><div className="vs">{p.period}</div></div>
          </div>
          {/* 목적(기본값) + 그 위에 AI가 풍부하게 보충 설명 */}
          {p.purpose && (
            <div className="block">
              <h3 className="block-h"><span className="dot" />이 사업이 뭔가요?</h3>
              <p className="body">{p.purpose}</p>
              {aiState === "pending" && (
                <p className="body" style={{ fontSize: 13, color: "var(--muted)", marginTop: 8 }}>✨ AI가 더 자세히 풀어드리는 중…</p>
              )}
              {aiState === "done" && aiText && (
                <div style={{ marginTop: 10, padding: "12px 14px", background: "var(--accent-soft)", borderRadius: 12, border: "1px solid rgba(49,130,246,.16)" }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--accent-ink)", marginBottom: 6 }}>✨ AI가 더 풀어서 설명해요</div>
                  <p className="body" style={{ margin: 0, fontSize: 14.5, color: "var(--ink2)" }}>{aiText}</p>
                </div>
              )}
            </div>
          )}
          {/* 대상 (분리된 필드) */}
          {p.targetDetail && <div className="block"><h3 className="block-h"><span className="dot" />누가 신청할 수 있나요?</h3><p className="body">{p.targetDetail}</p></div>}
          {/* 지원내용 (분리된 필드) */}
          {p.benefits && <div className="block"><h3 className="block-h"><span className="dot" />무엇을 지원받나요?</h3><p className="body">{p.benefits}</p></div>}
          <div className="block">
            <h3 className="block-h"><span className="dot" />나는 무엇을 준비하나요?</h3>
            <p className="body" style={{ marginBottom: 14 }}>
              {haveN === 0
                ? <>준비물 <b>{p.prepare.length}가지</b>를 새로 준비해야 해요.</>
                : haveN === p.prepare.length
                  ? <>준비물 <b style={{ color: "var(--green)" }}>{p.prepare.length}가지</b>는 보통 이미 갖고 계신 서류예요.</>
                  : <>준비물 {p.prepare.length}가지 중 <b style={{ color: "var(--green)" }}>{haveN}가지</b>는 보통 이미 갖고 계세요.</>}
            </p>
            <div className="prep">{p.prepare.map((x, i) => <div key={i} className={`prep-item ${x.status}`}>
              <div className="box"><Icon name={x.status === "have" ? "check" : "doc"} size={16} stroke={2.6} /></div>
              <span className="lab">{x.label}</span>
              <span className="st">{x.status === "have" ? "보유 가능" : "준비 필요"}</span>
            </div>)}</div>
          </div>
          <div className="block">
            <h3 className="block-h"><span className="dot" />신청은 이렇게 진행돼요</h3>
            <div className="steps">{p.steps.map((s, i) => <div className="step" key={i}><div className="num">{i + 1}</div><div className="stxt">{s}</div></div>)}</div>
          </div>
          {p.legalBasis && p.legalBasis.length > 0 && (
            <div className="block">
              <h3 className="block-h"><span className="dot" style={{ background: "#4F46E5" }} />근거 법령</h3>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {p.legalBasis.map((law, i) => <span key={i} className="tcat" style={{ background: "#EEF2FF", color: "#4F46E5" }}><Icon name="shield" size={12} />{law}</span>)}
              </div>
            </div>
          )}
          {p.note && <div className="callout"><Icon name="alert" size={20} className="ic" /><p>{p.note}</p></div>}
        </div>
        <div className="sheet-foot">
          {p.url && <Btn variant="primary" full iconRight="arrow-right" onClick={() => window.open(p.url, "_blank")}>공고 원문 보기</Btn>}
        </div>
      </aside>
    </>
  );
}

/* ══════════════════════════════════════════════
   P6  LEGAL BASIS PANEL (법령 기반 필터)
   ══════════════════════════════════════════════ */
function LegalBasisPanel({ onOpenPolicy }) {
  const lawMap = {};
  POLICIES.forEach(p => {
    (p.legalBasis || []).forEach(law => {
      if (!lawMap[law]) lawMap[law] = { count: 0, policies: [] };
      lawMap[law].count++;
      if (lawMap[law].policies.length < 3) lawMap[law].policies.push(p);
    });
  });
  const lawRows = Object.entries(lawMap).sort((a, b) => b[1].count - a[1].count);
  const withLaw = POLICIES.filter(p => p.legalBasis && p.legalBasis.length > 0).length;

  if (lawRows.length === 0) return null;

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panel-h">
        <h3>근거 법령별 사업 분포</h3>
        <span className="muted">{withLaw}건이 법령 근거 보유 · {lawRows.length}개 법령</span>
      </div>
      <div className="agency-list">
        {lawRows.slice(0, 12).map(([law, v]) => (
          <div className="agency-row" key={law} style={{ cursor: "pointer" }}
            onClick={() => v.policies[0] && onOpenPolicy(v.policies[0])}>
            <div className="agency-ic" style={{ background: "#EEF2FF", color: "#4F46E5" }}>
              <Icon name="shield" size={16} />
            </div>
            <div className="agency-name">{law}</div>
            <div className="agency-count">{v.count}건</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════
   P6  PLANNER (전문가 브리핑)
   ══════════════════════════════════════════════ */
function Planner({ onOpenPolicy }) {
  const total = POLICIES.length;
  const agencies = [...new Set(POLICIES.map(p => p.org))];
  const urgent = POLICIES.filter(p => p.dday != null && p.dday >= 0 && p.dday <= 14);
  const catMap = {};
  POLICIES.forEach(p => { catMap[p.category] = (catMap[p.category] || 0) + 1; });
  const cats = Object.entries(catMap).sort((a, b) => b[1] - a[1]);
  const catMax = Math.max(...cats.map(c => c[1]));

  // 기관별 집계
  const agMap = {};
  POLICIES.forEach(p => {
    const a = agMap[p.org] = agMap[p.org] || { count: 0, cats: new Set() };
    a.count++; a.cats.add(p.category);
  });
  const agRows = Object.entries(agMap).map(([org, v]) => ({ org, ...v })).sort((a, b) => b.count - a.count);
  const agMax = Math.max(...agRows.map(a => a.count));

  return (
    <div className="page rise">
      <div className="pro-head">
        <div className="eyebrow"><Icon name="chart" size={15} />정책 입안자 브리핑</div>
        <h1>지원사업 현황을 한 장으로 브리핑</h1>
        <p>운영 중인 사업을 주제·기관별로 비교하고 요약해 드려요.</p>
      </div>

      <div className="brief-box">
        <div className="brief-ic"><Icon name="spark" size={20} /></div>
        <div><h4>현황 요약</h4>
          <p>현재 <b>{total}개</b> 지원사업을 <b>{agencies.length}개 기관</b>이 운영 중입니다.
            주제별로는 <b>{cats[0]?.[0]}·{cats[1]?.[0]}</b> 비중이 가장 높고, <b>2주 내 마감 {urgent.length}건</b>이 임박했습니다.</p>
        </div>
      </div>

      <div className="kpi-grid">
        <div className="kpi"><div className="kpi-k">운영 중 사업</div><div className="kpi-v">{total}<span>건</span></div></div>
        <div className="kpi"><div className="kpi-k">운영 기관</div><div className="kpi-v">{agencies.length}<span>곳</span></div></div>
        <div className="kpi"><div className="kpi-k">2주 내 마감</div><div className="kpi-v" style={{ color: "var(--amber)" }}>{urgent.length}<span>건</span></div></div>
      </div>

      <div className="pro-2col">
        <div className="panel">
          <div className="panel-h"><h3>주제별 사업 분포</h3><span className="muted">사업 수 기준</span></div>
          <div className="barlist">{cats.map(([c, n]) => <BarRow key={c} label={c} value={n} max={catMax} suffix="건" raw />)}</div>
        </div>
        <div className="panel">
          <div className="panel-h"><h3>주요 운영 기관 TOP 8</h3><span className="muted">사업 수 기준</span></div>
          <div className="agency-list">
            {agRows.slice(0, 8).map(a => (
              <div className="agency-row" key={a.org}>
                <div className="agency-ic"><Icon name="building" size={18} /></div>
                <div className="agency-name">{a.org}<span>{[...a.cats].slice(0, 3).join(" · ")}</span></div>
                <div className="agency-count">{a.count}개</div>
                <div className="agency-bar"><i style={{ width: Math.max(6, (a.count / agMax) * 100) + "%" }} /></div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 법령 기반 필터 (정책입안자 전용) */}
      <LegalBasisPanel onOpenPolicy={onOpenPolicy} />

      <div className="disclaimer" style={{ marginTop: 16 }}>관리자 문의량 지표는 시연용 가상치입니다. 실제 운영 시 데이터 연동이 필요합니다.</div>
    </div>
  );
}

/* ══════════════════════════════════════════════
   P6  STAFF MODE (상담·관리자)
   ══════════════════════════════════════════════ */
const STAFF_FIELDS = [
  { id: "industry", label: "업종" }, { id: "stage", label: "사업 단계" },
  { id: "goal", label: "문의 목적" }, { id: "region", label: "지역" },
].map(f => ({ ...f, opts: (QUESTIONS.find(q => q.id === f.id) || {}).options || [] }));

function StaffMode({ onOpenPolicy }) {
  const [sel, setSel] = useState({});
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);
  const set = (k, v) => setSel(s => ({ ...s, [k]: s[k] === v ? undefined : v }));

  function run() {
    const list = computeMatches(sel);
    setResult(list.length ? {
      top: list[0], count: list.length,
      ableCount: list.filter(p => p.eligible === "able").length,
      list: list.slice(0, 5),
    } : { count: 0, list: [] });
    setCopied(false);
  }

  function copy() {
    if (!result || !result.count) return;
    const t = result.top;
    const amt = window.amountText(t);
    const txt = `[민원인 대상 추천]\n조건에 맞는 지원사업 총 ${result.count}건, 그중 ${result.ableCount}건 바로 신청 가능.\n\n가장 적합: ${t.title} (${t.org})\n· 지원: ${amt}\n· 기간: ${t.period}\n· 안내: ${t.note}`;
    navigator.clipboard?.writeText(txt); setCopied(true); setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="page rise">
      <div className="pro-head">
        <div className="eyebrow"><Icon name="headset" size={15} />상담·관리자 모드</div>
        <h1>빠르게 조회·답변하세요</h1>
        <p>민원인의 조건을 입력하면 적합 사업과 답변 스크립트를 만들어요.</p>
      </div>
      <div className="staff-grid">
        <div className="staff-panel sticky">
          <h3>민원인 조건 입력</h3>
          {STAFF_FIELDS.map(f => <div className="field" key={f.id}><label>{f.label}</label>
            <div className="field-opts">{f.opts.map(o => <Chip key={o.id} active={sel[f.id] === o.id} onClick={() => set(f.id, o.id)}>{o.label}</Chip>)}</div>
          </div>)}
          <Btn variant="primary" full icon="search" onClick={run}>적합 사업 조회</Btn>
        </div>
        <div>
          {!result && <div className="staff-panel"><div className="staff-empty">
            <div className="ic"><Icon name="headset" size={28} /></div>
            <h3>조건을 선택하고 조회해 주세요</h3>
            <p>민원인의 업종·단계·목적을 고른 뒤 '적합 사업 조회'를 누르면 추천 사업과 답변 스크립트가 나타나요.</p>
          </div></div>}
          {result && result.count === 0 && <div className="staff-panel"><div className="staff-empty">
            <div className="ic"><Icon name="compass" size={28} /></div>
            <h3>조건에 맞는 사업이 없어요</h3>
            <p>조건을 넓히거나, 민원인에게 새 공고 알림 신청을 안내해 주세요.</p>
          </div></div>}
          {result && result.count > 0 && <div className="fade">
            <div className="script-card">
              <div className="sh"><span className="t"><Icon name="spark" size={16} />답변 스크립트</span>
                <button className="cp" onClick={copy}><Icon name={copied ? "check" : "copy"} size={15} />{copied ? "복사됨" : "복사"}</button></div>
              <p>조건에 맞는 지원사업은 총 <span className="hl">{result.count}건</span>이며, 그중 <span className="hl">{result.ableCount}건</span>은 바로 신청 가능합니다.</p>
              <p>가장 적합한 사업은 <span className="hl">{result.top.title}</span>({result.top.org})입니다. {window.amountText(result.top, true)} {result.top.period} 기준입니다.</p>
            </div>
            <div className="results-toolbar" style={{ marginTop: 4 }}><span className="count">적합 사업 {result.count}건 (상위 5건)</span></div>
            <div className="results-list" style={{ gridTemplateColumns: "1fr" }}>
              {result.list.map(p => <PolicyCard key={p.id} p={p} showMatch onClick={() => onOpenPolicy(p)} />)}
            </div>
          </div>}
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════
   APP ROOT + ROUTING
   ══════════════════════════════════════════════ */
function App() {
  const [route, setRoute] = useState("loading");
  const [ctx, setCtx] = useState({ userType: null, seed: "" });
  const [answers, setAnswers] = useState(null);
  const [queryText, setQueryText] = useState("");  // 자유질의 원문 — Results 어휘 리랭크용
  const [openP, setOpenP] = useState(null);

  const mode = route === "staff" ? "staff" : route === "planner" ? "planner" : "user";
  function go(r) { setRoute(r); window.scrollTo({ top: 0 }); }
  function hasPolicyLookupIntent(text) {
    return /관련\s*(정책|공고|지원|사업)|지원\s*(정책|공고|사업)|정책\s*(알려|추천|찾아|뭐|전체)|공고\s*(알려|추천|찾아|뭐|전체)|뭐\s*(있|있어|있나)|알려줘|추천해줘|찾아줘|전체\s*알려/.test(text || "");
  }
  function hasUsablePolicyConditions(prefill) {
    return !!(prefill && (prefill.goal || prefill.industry || prefill.region || prefill.stage));
  }
  function startDiagnose(seed) {
    const text = seed || "";
    const prefill = parseSeed(text);
    if (text.trim() && hasPolicyLookupIntent(text) && hasUsablePolicyConditions(prefill)) {
      setQueryText(text);
      setAnswers(prefill);
      go("results");
      return;
    }
    setQueryText("");
    setCtx({ userType: null, seed: text, prefill, questions: null });
    go("diagnose");
  }
  function pickType(id) {
    const prof = TYPE_PROFILE[id] || {};
    setCtx({ userType: id, seed: "", prefill: prof.prefill || {}, questions: questionsForType(id) });
    go("diagnose");
  }

  // 데이터 로드 (dday 동적 계산)
  useEffect(() => {
    fetch("../policyfit-db.json?v=" + Date.now())
      .then(r => r.json())
      .then(data => {
        // 소상공인 무관(연구기관·중후장대 산업 등, LLM 판정)으로 표시된 공고는 전 화면에서 제외
        window.POLICIES = data
          .filter(p => p.smallBizRelevant !== false)
          .map(p => ({ ...p, dday: computeDday(p.endDate) }));
        setRoute("home");
      })
      .catch(err => {
        console.error("Failed to load policyfit-db.json:", err);
        setRoute("error");
      });
  }, []);

  const ROLES = [
    { id: "user", label: "이용자", icon: "person", route: "home" },
    { id: "staff", label: "상담·관리", icon: "headset", route: "staff" },
    { id: "planner", label: "정책 입안", icon: "chart", route: "planner" },
  ];

  if (route === "loading") return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", flexDirection: "column", gap: 16 }}>
      <div className="logo-mark" style={{ width: 56, height: 56, borderRadius: 16, fontSize: 28 }}><Icon name="spark" size={28} stroke={2.4} /></div>
      <p style={{ color: "var(--muted)", fontSize: 14 }}>정책 데이터를 불러오는 중...</p>
    </div>
  );

  if (route === "error") return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", flexDirection: "column", gap: 16 }}>
      <p style={{ color: "var(--red)", fontSize: 16, fontWeight: 600 }}>데이터 로드 실패</p>
      <p style={{ color: "var(--muted)", fontSize: 14 }}>policyfit-db.json 파일을 확인해주세요. <br />서버: python -m http.server 8090 --directory outputs</p>
    </div>
  );

  return (
    <div>
      <header className="appbar"><div className="appbar-inner">
        <div className="logo" onClick={() => go("home")}><span className="logo-mark"><Icon name="spark" size={18} stroke={2.4} /></span>정책<b>핏</b></div>
        {mode === "user" && <nav className="appbar-nav">
          <button className={route === "home" ? "on" : ""} onClick={() => go("home")}>홈</button>
          <button className={(route === "diagnose" || route === "results") ? "on" : ""} onClick={() => startDiagnose("")}>맞춤 진단</button>
        </nav>}
        <span className="appbar-spacer" />
        <div className="mode-switch">{ROLES.map(r => <button key={r.id} className={mode === r.id ? "on" : ""} onClick={() => go(r.route)}>
          <Icon name={r.icon} size={16} />{r.label}
        </button>)}</div>
      </div></header>

      {route === "home" && <Home onStart={startDiagnose} onPickType={pickType} onOpenPolicy={setOpenP} onBrowse={() => { setQueryText(""); setAnswers({}); go("results"); }} />}
      {route === "diagnose" && <Diagnose key={JSON.stringify(ctx)} userType={ctx.userType} seed={ctx.seed} prefill={ctx.prefill} questions={ctx.questions}
        onComplete={a => { setQueryText(""); setAnswers(a); go("results"); }} onBack={() => go("home")} />}
      {route === "results" && answers && <Results answers={answers} query={queryText} onOpenPolicy={setOpenP} onRedo={() => go("diagnose")} onDiagnose={() => startDiagnose("")} />}
      {route === "staff" && <StaffMode onOpenPolicy={setOpenP} />}
      {route === "planner" && <Planner onOpenPolicy={setOpenP} />}

      {openP && <Detail p={openP} onClose={() => setOpenP(null)} />}

      {/* 모바일 하단 탭바 (CSS에서 480px 이하에서만 display:flex) */}
      <nav className="mob-tab">
        <button className={route === "home" ? "on" : ""} onClick={() => go("home")}>
          <Icon name="spark" size={22} /><span>홈</span>
        </button>
        <button className={(route === "diagnose" || route === "results") ? "on" : ""} onClick={() => startDiagnose("")}>
          <Icon name="target" size={22} /><span>진단</span>
        </button>
        <button className={route === "staff" ? "on" : ""} onClick={() => go("staff")}>
          <Icon name="headset" size={22} /><span>상담</span>
        </button>
        <button className={route === "planner" ? "on" : ""} onClick={() => go("planner")}>
          <Icon name="chart" size={22} /><span>브리핑</span>
        </button>
      </nav>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
