import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const ROOT = path.resolve(path.dirname(__filename), "..");
const OUT_DIR = path.join(ROOT, "outputs");
const DB_PATH = path.join(OUT_DIR, "policyfit-db.json");
const CONFIG_PATH = path.join(OUT_DIR, "policyfit", "policyfit-config.js");

const SPECIFIC_REGIONS = [
  { id: "seoul", label: "서울", query: "서울 지역 공고 전체 알려줘" },
  { id: "incheon", label: "인천", query: "인천 지역 공고 전체 알려줘" },
  { id: "gyeonggi", label: "경기", query: "경기 지역 공고 전체 알려줘" },
  { id: "busan", label: "부산", query: "부산 지역 공고 전체 알려줘" },
  { id: "daegu", label: "대구", query: "대구 지역 공고 전체 알려줘" },
  { id: "daejeon", label: "대전", query: "대전 지역 공고 전체 알려줘" },
  { id: "gwangju", label: "광주", query: "광주 지역 공고 전체 알려줘" },
  { id: "ulsan", label: "울산", query: "울산 지역 공고 전체 알려줘" },
  { id: "sejong", label: "세종", query: "세종 지역 공고 전체 알려줘" },
  { id: "gangwon", label: "강원", query: "강원 지역 공고 전체 알려줘" },
  { id: "chungbuk", label: "충북", query: "충북 지역 공고 전체 알려줘" },
  { id: "chungnam", label: "충남", query: "충남 지역 공고 전체 알려줘" },
  { id: "jeonbuk", label: "전북", query: "전북 지역 공고 전체 알려줘" },
  { id: "jeonnam", label: "전남", query: "전남 지역 공고 전체 알려줘" },
  { id: "gyeongbuk", label: "경북", query: "경북 지역 공고 전체 알려줘" },
  { id: "gyeongnam", label: "경남", query: "경남 지역 공고 전체 알려줘" },
  { id: "jeju", label: "제주", query: "제주 지역 공고 전체 알려줘" },
];

const SCENARIOS = [
  { id: "banseok_cafe", query: "반석동 카페 운영하는데 관련 정책 알려줘", expectMode: "national_first", expectRegionId: "daejeon" },
  { id: "dunsan_operating_cafe", query: "둔산동 카페 운영하는데 관련 정책 알려줘", expectMode: "national_first", expectRegionId: "daejeon", expectNoStartupTop: true },
  { id: "daejeon_only", query: "대전 지역 공고 전체 알려줘", expectMode: "strict", expectRegionId: "daejeon" },
  { id: "dunsan_food_startup", query: "둔산동에서 창업 준비중이야. 음식점", expectMode: "national_first", expectRegionId: "daejeon" },
  { id: "gwangju_cafe_fund", query: "광주 카페 운영자금 알려줘", expectMode: "national_first", expectRegionId: "gwangju" },
  { id: "marketing_only", query: "마케팅 지원 알려줘", expectMode: "none", expectNationalFirst: true },
  { id: "national_marketing", query: "전국 마케팅 지원 알려줘", expectMode: "national_only" },
];

function loadEngine() {
  const context = { console, window: {} };
  context.window.window = context.window;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(CONFIG_PATH, "utf8"), context, { filename: CONFIG_PATH });
  const data = JSON.parse(fs.readFileSync(DB_PATH, "utf8"));
  context.window.POLICIES = data.map(p => ({ ...p, dday: context.window.computeDday(p.endDate) }));
  context.POLICIES = context.window.POLICIES;
  return context.window;
}

function countBy(items, getter) {
  const out = {};
  for (const item of items) {
    const keys = getter(item);
    for (const key of Array.isArray(keys) ? keys : [keys]) {
      const safeKey = key || "(empty)";
      out[safeKey] = (out[safeKey] || 0) + 1;
    }
  }
  return Object.fromEntries(Object.entries(out).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])));
}

function samplePolicy(p) {
  return {
    id: p.id,
    title: p.title,
    org: p.org,
    regions: p.regions || [],
    goals: p.goals || [],
    tags: p.tags || [],
    category: p.category,
    specificRegionIds: p._specificRegionIds || [],
    specialTargets: p._specialTargets || [],
  };
}

function isCrossRegion(policyIds, expectedId) {
  return policyIds.length > 0 && !policyIds.includes(expectedId);
}

function auditDb(engine) {
  const policies = engine.POLICIES.map(p => ({
    ...p,
    _specificRegionIds: engine.policySpecificRegionIds(p),
    _specialTargets: engine.policySpecialTargets(p),
    _regionHints: engine.policyRegionHints(p),
  }));

  const issues = {
    anyWithSpecificRegion: [],
    specificRegionWithoutDeclaredGroup: [],
    specialTargetPolicies: [],
    missingClassification: [],
  };

  for (const p of policies) {
    const regions = p.regions || [];
    if (regions.includes("any") && p._specificRegionIds.length) {
      issues.anyWithSpecificRegion.push(samplePolicy(p));
    }
    if (!p.goals?.length || !p.tags?.length || !p.regions?.length) {
      issues.missingClassification.push(samplePolicy(p));
    }
    if (p._specialTargets.length) {
      issues.specialTargetPolicies.push(samplePolicy(p));
    }
    if (p._specificRegionIds.length) {
      const allowedGroups = new Set();
      for (const id of p._specificRegionIds) {
        const regionSpec = SPECIFIC_REGIONS.find(r => r.id === id);
        if (!regionSpec) continue;
        const ans = engine.parseSeed(regionSpec.query);
        if (ans.region) allowedGroups.add(ans.region);
      }
      const hasDeclaredGroup = regions.some(r => allowedGroups.has(r) || r === "any");
      if (!hasDeclaredGroup) issues.specificRegionWithoutDeclaredGroup.push(samplePolicy(p));
    }
  }

  return {
    total: policies.length,
    byRegionField: countBy(policies, p => p.regions || []),
    bySpecificRegionId: countBy(policies.filter(p => p._specificRegionIds.length), p => p._specificRegionIds),
    byGoal: countBy(policies, p => p.goals || []),
    byTag: countBy(policies, p => p.tags || []),
    byCategory: countBy(policies, p => p.category),
    issues,
  };
}

function auditRegionQueries(engine) {
  return SPECIFIC_REGIONS.map(region => {
    const ans = engine.parseSeed(region.query);
    const mode = engine.regionMatchMode(ans);
    const list = engine.computeMatches(ans);
    const incompatible = list
      .filter(p => isCrossRegion(engine.policySpecificRegionIds(p), region.id))
      .map(samplePolicy);
    return {
      ...region,
      parsed: ans,
      mode,
      count: list.length,
      incompatibleCount: incompatible.length,
      incompatible: incompatible.slice(0, 20),
      top5: list.slice(0, 5).map(p => ({
        title: p.title,
        org: p.org,
        regionClass: p._regionClass,
        specificRegionIds: engine.policySpecificRegionIds(p),
      })),
    };
  });
}

function auditScenarios(engine) {
  return SCENARIOS.map(s => {
    const ans = engine.parseSeed(s.query);
    const mode = engine.regionMatchMode(ans);
    const list = engine.computeMatches(ans);
    const nationalCount = list.filter(p => p._regionClass === "national" || p._regionClass === "national-only").length;
    const regionalCount = list.filter(p => p._regionClass === "regional" || p._regionClass === "regional-only").length;
    const topClasses = list.slice(0, 10).map(p => p._regionClass);
    const crossRegion = s.expectRegionId
      ? list.filter(p => isCrossRegion(engine.policySpecificRegionIds(p), s.expectRegionId)).map(samplePolicy)
      : [];
    const specialLeakage = list.filter(p => engine.policySpecialTargets(p).length && !(ans._matchMeta?.specialTargets || []).length).map(samplePolicy);
    const startupTopLeakage = s.expectNoStartupTop
      ? list.slice(0, 10).filter(p => engine.policyLifecycleTargets(p).some(t => t === "prestart" || t === "startup")).map(samplePolicy)
      : [];
    const failures = [];
    if (s.expectMode && mode !== s.expectMode) failures.push(`mode=${mode}, expected=${s.expectMode}`);
    if (s.expectNationalFirst && topClasses[0] !== "national") failures.push(`topClass=${topClasses[0]}, expected=national`);
    if (crossRegion.length) failures.push(`crossRegion=${crossRegion.length}`);
    if (specialLeakage.length) failures.push(`specialTargetLeakage=${specialLeakage.length}`);
    if (startupTopLeakage.length) failures.push(`startupTopLeakage=${startupTopLeakage.length}`);
    return {
      ...s,
      parsed: ans,
      mode,
      count: list.length,
      nationalCount,
      regionalCount,
      topClasses,
      failures,
      crossRegion: crossRegion.slice(0, 20),
      specialLeakage: specialLeakage.slice(0, 20),
      startupTopLeakage: startupTopLeakage.slice(0, 20),
      top5: list.slice(0, 5).map(p => ({
        title: p.title,
        org: p.org,
        regionClass: p._regionClass,
        specificRegionIds: engine.policySpecificRegionIds(p),
      })),
    };
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderHtml(report) {
  const regionRows = report.regionQueries.map(r => `
    <tr class="${r.incompatibleCount ? "bad" : "ok"}">
      <td>${escapeHtml(r.label)}</td>
      <td>${escapeHtml(r.mode)}</td>
      <td>${r.count}</td>
      <td>${r.incompatibleCount}</td>
      <td>${r.top5.map(x => escapeHtml(x.title)).join("<br>")}</td>
    </tr>`).join("");
  const scenarioRows = report.scenarios.map(s => `
    <tr class="${s.failures.length ? "bad" : "ok"}">
      <td>${escapeHtml(s.id)}</td>
      <td>${escapeHtml(s.query)}</td>
      <td>${escapeHtml(s.mode)}</td>
      <td>${s.count}</td>
      <td>${s.nationalCount}/${s.regionalCount}</td>
      <td>${s.failures.length ? escapeHtml(s.failures.join(", ")) : "PASS"}</td>
    </tr>`).join("");
  const issueCards = Object.entries(report.db.issues).map(([key, items]) => `
    <section>
      <h2>${escapeHtml(key)} <span>${items.length}건</span></h2>
      <ol>${items.slice(0, 30).map(x => `<li><b>${escapeHtml(x.id)}</b> ${escapeHtml(x.title)} <small>${escapeHtml((x.specificRegionIds || []).join(","))}</small></li>`).join("")}</ol>
    </section>`).join("");
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolicyFit 매칭 전수 검증</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;margin:0;background:#f6f7fb;color:#111827}
main{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:28px;margin:0 0 8px} h2{font-size:18px;margin:26px 0 10px} h2 span{color:#2563eb}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:18px 0}
.metric{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}.metric b{display:block;font-size:24px}.metric span{color:#6b7280;font-size:13px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top;font-size:13px}
th{background:#f9fafb;color:#374151}.bad td:first-child{border-left:4px solid #dc2626}.ok td:first-child{border-left:4px solid #059669}
section{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px;margin:12px 0} li{margin:6px 0} small{color:#6b7280}
code{background:#eef2ff;padding:1px 5px;border-radius:5px}
</style>
</head>
<body><main>
<h1>PolicyFit 매칭 전수 검증</h1>
<p>생성: ${escapeHtml(report.generatedAt)} / DB: <code>${escapeHtml(path.basename(DB_PATH))}</code></p>
<div class="summary">
  <div class="metric"><b>${report.db.total}</b><span>전체 공고</span></div>
  <div class="metric"><b>${report.regionQueries.reduce((n, r) => n + r.incompatibleCount, 0)}</b><span>지역 질의 교차오염</span></div>
  <div class="metric"><b>${report.scenarios.filter(s => s.failures.length).length}</b><span>시나리오 실패</span></div>
  <div class="metric"><b>${report.db.issues.anyWithSpecificRegion.length}</b><span>지역명 포함 any 공고</span></div>
</div>
<h2>지역 제한 질의 검증</h2>
<table><thead><tr><th>지역</th><th>모드</th><th>결과 수</th><th>다른 지역 섞임</th><th>상위 5건</th></tr></thead><tbody>${regionRows}</tbody></table>
<h2>대표 시나리오 검증</h2>
<table><thead><tr><th>ID</th><th>질의</th><th>모드</th><th>결과 수</th><th>전국/지역</th><th>판정</th></tr></thead><tbody>${scenarioRows}</tbody></table>
<h2>DB 패턴 이슈</h2>
${issueCards}
</main></body></html>`;
}

function main() {
  const engine = loadEngine();
  const report = {
    generatedAt: new Date().toISOString(),
    dbPath: DB_PATH,
    configPath: CONFIG_PATH,
    db: auditDb(engine),
    regionQueries: auditRegionQueries(engine),
    scenarios: auditScenarios(engine),
  };
  const outJson = path.join(OUT_DIR, "policyfit-matching-audit.json");
  const outHtml = path.join(OUT_DIR, "policyfit-matching-audit.html");
  fs.writeFileSync(outJson, JSON.stringify(report, null, 2), "utf8");
  fs.writeFileSync(outHtml, renderHtml(report), "utf8");

  const crossRegion = report.regionQueries.reduce((n, r) => n + r.incompatibleCount, 0);
  const scenarioFailures = report.scenarios.filter(s => s.failures.length);
  console.log(`PolicyFit matching audit`);
  console.log(`- policies: ${report.db.total}`);
  console.log(`- region query cross-region issues: ${crossRegion}`);
  console.log(`- scenario failures: ${scenarioFailures.length}`);
  console.log(`- any-with-specific-region DB warnings: ${report.db.issues.anyWithSpecificRegion.length}`);
  console.log(`- report: ${path.relative(ROOT, outJson)}`);
  console.log(`- html: ${path.relative(ROOT, outHtml)}`);
  if (crossRegion || scenarioFailures.length) {
    process.exitCode = 1;
  }
}

main();
