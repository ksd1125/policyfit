/**
 * policyfit-ui.jsx
 * ─────────────────────────────────────────────
 * 공통 UI 프리미티브: Icon, Btn, Chip, Avatar, 배지 등
 * type="text/babel"로 로드
 */

/* ══════════════════════════════════════════════
   ICON SET (stroke-based, 24×24 viewBox)
   ══════════════════════════════════════════════ */
function Icon({ name, size = 24, stroke = 2, style, className }) {
  const p = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: stroke, strokeLinecap: "round",
    strokeLinejoin: "round", style, className,
    "aria-hidden": "true", focusable: "false",   // 장식 아이콘 — 스크린리더 무시
  };
  const paths = {
    spark:        <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/>,
    "arrow-right":<path d="M5 12h14M13 6l6 6-6 6"/>,
    "arrow-left": <path d="M19 12H5M11 18l-6-6 6-6"/>,
    check:        <path d="M20 6L9 17l-5-5"/>,
    "check-circle":<><circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/></>,
    alert:        <><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></>,
    won:          <path d="M4 6l3 12 3-9 2 9 3-12M3 10h18M3 14h18"/>,
    coins:        <><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
    bulb:         <path d="M9 18h6M10 21h4M12 3a6 6 0 00-4 10.5c.7.6 1 1.2 1 2.5h6c0-1.3.3-1.9 1-2.5A6 6 0 0012 3z"/>,
    monitor:      <><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></>,
    cap:          <><path d="M2 9l10-5 10 5-10 5L2 9z"/><path d="M6 11.5V16c0 1.2 2.7 2.5 6 2.5s6-1.3 6-2.5v-4.5M22 9v5"/></>,
    globe:        <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 4 6 4 9s-1.4 6.4-4 9c-2.6-2.6-4-6-4-9s1.4-6.4 4-9z"/></>,
    refresh:      <path d="M21 12a9 9 0 11-2.6-6.4M21 4v4.5h-4.5"/>,
    calendar:     <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></>,
    doc:          <><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></>,
    search:       <><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></>,
    send:         <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>,
    store:        <><path d="M4 9l1-4h14l1 4M4 9v10a1 1 0 001 1h14a1 1 0 001-1V9M4 9h16M9 20v-6h6v6"/></>,
    shop:         <><path d="M4 10v9a1 1 0 001 1h14a1 1 0 001-1v-9"/><path d="M3 10l2-5.5h14L21 10a2.4 2.4 0 01-4.3 1.4 2.4 2.4 0 01-4.3 0 2.4 2.4 0 01-4.3 0A2.4 2.4 0 013 10z"/></>,
    chart:        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>,
    users:        <><circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0112 0M16 6a3 3 0 010 6M21 20a6 6 0 00-5-5.9"/></>,
    building:     <><rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h.01M13 7h.01M9 11h.01M13 11h.01M9 15h.01M13 15h.01M9 21v-3h6v3"/></>,
    person:       <><circle cx="12" cy="8" r="3.2"/><path d="M5 20a7 7 0 0114 0"/></>,
    headset:      <><path d="M4 13v-1a8 8 0 0116 0v1M4 13a2 2 0 012 2v2a2 2 0 01-2 2 2 2 0 01-2-2v-2a2 2 0 012-2zM20 13a2 2 0 00-2 2v2a2 2 0 002 2 2 2 0 002-2v-2a2 2 0 00-2-2zM18 19a4 4 0 01-4 3h-2"/></>,
    shield:       <><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></>,
    tag:          <><path d="M3 7v5l9 9 7-7-9-9H3z"/><circle cx="7.5" cy="9.5" r="1.2"/></>,
    clock:        <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    copy:         <><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h8"/></>,
    bookmark:     <path d="M6 4h12v16l-6-4-6 4V4z"/>,
    x:            <path d="M6 6l12 12M18 6L6 18"/>,
    filter:       <path d="M3 5h18l-7 8v6l-4-2v-4L3 5z"/>,
    target:       <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
    bell:         <><path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6zM10 20a2 2 0 004 0"/></>,
    compass:      <><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5 5-2z"/></>,
    rocket:       <><path d="M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2M9 11a4 4 0 015.5-5.5C17 4 20 4 20 4s0 3-1.5 5.5A4 4 0 0113 15l-2 1-3-3 1-2z"/><circle cx="15" cy="9" r="1"/></>,
  };
  return <svg {...p}>{paths[name] || null}</svg>;
}

/* ══════════════════════════════════════════════
   PRIMITIVES
   ══════════════════════════════════════════════ */
function Btn({ children, variant = "primary", size = "md", icon, iconRight, onClick, full, style }) {
  return (
    <button className={`btn btn-${variant} btn-${size}${full ? " btn-full" : ""}`} onClick={onClick} style={style}>
      {icon && <Icon name={icon} size={size === "lg" ? 20 : 18} />}
      {children && <span>{children}</span>}
      {iconRight && <Icon name={iconRight} size={size === "lg" ? 20 : 18} />}
    </button>
  );
}

function Chip({ children, active, onClick, count }) {
  return (
    <button className={`chip${active ? " chip-active" : ""}`} onClick={onClick}>
      {children}
      {count != null && <span className="chip-count">{count}</span>}
    </button>
  );
}

function Avatar({ size = 36 }) {
  return (
    <div className="pf-avatar" style={{ width: size, height: size }}>
      <Icon name="spark" size={size * 0.55} stroke={2.2} />
    </div>
  );
}

function MatchRing({ value, size = 46 }) {
  const r = (size - 6) / 2, c = 2 * Math.PI * r;
  return (
    <div className="match-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="4" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth="4"
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dashoffset .8s ease" }} />
      </svg>
      <span className="match-ring-num">{value}</span>
    </div>
  );
}

function EligibleBadge({ status }) {
  if (status === "able")  return <span className="elig elig-able"><Icon name="check-circle" size={15} />신청 가능</span>;
  if (status === "check") return <span className="elig elig-check"><Icon name="alert" size={15} />조건 확인 필요</span>;
  return <span className="elig elig-need"><Icon name="alert" size={15} />정보 더 필요</span>;
}

function DdayPill({ dday }) {
  if (dday == null) return <span className="dday dday-always"><Icon name="clock" size={13} />상시</span>;
  if (dday < 0) return <span className="dday dday-urgent"><Icon name="clock" size={13} />마감</span>;
  return <span className={`dday${dday <= 14 ? " dday-urgent" : ""}`}><Icon name="clock" size={13} />D-{dday}</span>;
}

function PolicyCard({ p, compact, onClick, showMatch }) {
  return (
    <button className={`pcard${compact ? " compact" : ""}`} onClick={onClick}>
      <div className="pcard-top">
        <div className="pcard-ic"><Icon name={CAT_ICON[p.category] || "doc"} size={24} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="pcard-cat">{p.category}</div>
          <h3>{p.title}</h3>
          <div className="org"><Icon name="building" size={13} />{p.org}</div>
        </div>
        {showMatch && p.pscore > 0 && <MatchRing value={p.pscore} />}
      </div>
      <p className="sum">{p.purpose || p.summary}</p>
      {p.targetShort && <span className="pcard-target"><Icon name="person" size={12} />{p.targetShort} 대상</span>}
      <div className="pcard-amount">
        <span className="amt-cap"><Icon name="won" size={14} />지원 규모{(["explicit_llm", "calculated_llm", "total_only_llm"].includes(p.amountSource) && !/공고 확인|확인 필요|규모 확인/.test(p.amountPerApplicant || p.amountLabel || "")) && <span className="amt-trust" title="공고 원문에서 AI가 확인한 금액"><Icon name="check" size={10} stroke={3} />확인</span>}</span>
        <span className="num">{p.amountPerApplicant || p.amountLabel}</span>
        {p.amountSource && p.amountSource.startsWith("calculated") && p.amountTotal && p.amountTargetCount && (
          <span className="amt-sub">총 {p.amountTotal} ÷ {p.amountTargetCount}</span>
        )}
        {p.amountSource && p.amountSource.startsWith("total_only") && p.amountTotal && (
          <span className="amt-sub">총사업비 기준</span>
        )}
      </div>
      <div className="pcard-foot">
        <EligibleBadge status={p.eligible} />
        <span className="spacer" />
        <DdayPill dday={p.dday} />
      </div>
    </button>
  );
}

function BarRow({ label, value, max, suffix, accent, rank, raw }) {
  const pct = Math.max(3, Math.round((value / max) * 100));
  // raw=true면 카운트(정수)이므로 통화 포맷(krw) 미적용
  const shown = raw ? value.toLocaleString("ko-KR") : krw(value);
  return (
    <div className="bar-row">
      <div className="bar-label">
        {rank != null && <span className="bar-rank">{rank}</span>}
        <span>{label}</span>
      </div>
      <div className="bar-track">
        <i style={{ width: pct + "%", background: accent || "var(--accent)" }} />
      </div>
      <div className="bar-val">{shown}{suffix || ""}</div>
    </div>
  );
}

/* ── Export ── */
Object.assign(window, {
  Icon, Btn, Chip, Avatar, MatchRing, EligibleBadge, DdayPill, PolicyCard, BarRow,
});
