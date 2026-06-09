import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  classifyNotice,
  countBy,
  getLatestRunId,
  loadItemsForRun,
  sortCountEntries,
} from "./lib/notice-analysis.js";

function topLines(entries, limit = 10) {
  return entries
    .slice(0, limit)
    .map(([name, count]) => `- ${name}: ${count}건`)
    .join("\n");
}

function buildMarkdown({ runId, total, counts }) {
  return `# 기업마당 공고 유형화 검토

- 분석 대상 runId: ${runId}
- 분석 공고 수: ${total}건

## 1. 문서유형
${topLines(counts.documentProfile)}

## 2. 지원유형
${topLines(counts.supportType)}

## 3. 대상유형
${topLines(counts.targetType)}

## 4. 접수유형
${topLines(counts.applicationType)}

## 5. 신청기간 유형
${topLines(counts.periodType)}

## 6. 권장 파싱 순서
1. 메타데이터 파싱: 공고명, 기관, 대상, 신청기간, 대분류/세부분류 확보
2. 상세 HTML 파싱: 사업개요, 신청방법, 문의처 우선 추출
3. 본문출력파일 파싱: HTML 누락 보강
4. 첨부파일 파싱: 제출서류, 유의사항, 제외조건, 세부 지원금액 보강

## 7. 권장 유형화 틀
- 문서구조유형: html_plus_print / hwp_core / pdf_core / bundle_package / mixed_attachment
- 지원유형: funding / consulting / commercialization / startup / facility / education_event / other
- 대상유형: small_business / startup_venture / sme / social_enterprise / other
- 접수유형: website / email / visit / post / fax / mixed / other
- 기간유형: date_range / always_open / budget_exhausted / announced_later / varies_by_program / other
`;
}

function buildHtml({ runId, total, counts }) {
  const section = (title, entries) => `
    <section>
      <h2>${title}</h2>
      <table>
        <thead><tr><th>유형</th><th>건수</th></tr></thead>
        <tbody>
          ${entries
            .slice(0, 20)
            .map(([name, count]) => `<tr><td>${name}</td><td>${count}</td></tr>`)
            .join("")}
        </tbody>
      </table>
    </section>`;

  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>기업마당 공고 유형화 검토</title>
  <style>
    body { font-family: "Malgun Gothic", sans-serif; margin: 24px; color: #1f2937; }
    h1, h2 { margin: 0 0 12px; }
    p { margin: 8px 0 16px; }
    section { margin-top: 24px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #d1d5db; padding: 8px; text-align: left; }
    th { background: #eff6ff; }
    code { background: #f3f4f6; padding: 2px 4px; }
  </style>
</head>
<body>
  <h1>기업마당 공고 유형화 검토</h1>
  <p>분석 대상 runId: <code>${runId}</code></p>
  <p>분석 공고 수: ${total}건</p>
  ${section("문서유형", counts.documentProfile)}
  ${section("지원유형", counts.supportType)}
  ${section("대상유형", counts.targetType)}
  ${section("접수유형", counts.applicationType)}
  ${section("신청기간 유형", counts.periodType)}
  <section>
    <h2>권장 파싱 순서</h2>
    <p>1. 메타데이터 파싱 2. 상세 HTML 파싱 3. 본문출력파일 파싱 4. 첨부파일 파싱</p>
  </section>
</body>
</html>`;
}

async function main() {
  const projectRoot = process.cwd();
  const apiRoot = path.join(projectRoot, "raw", "api");
  const runId = getLatestRunId(apiRoot);
  if (!runId) {
    throw new Error("No collection run found under raw/api");
  }

  const items = loadItemsForRun(projectRoot, runId);
  const classified = items.map(classifyNotice);

  const counts = {
    documentProfile: sortCountEntries(countBy(classified, "documentProfile")),
    supportType: sortCountEntries(countBy(classified, "supportType")),
    targetType: sortCountEntries(countBy(classified, "targetType")),
    applicationType: sortCountEntries(countBy(classified, "applicationType")),
    periodType: sortCountEntries(countBy(classified, "periodType")),
  };

  const outputBase = `notice-type-analysis-${runId}`;
  const outputDir = path.join(projectRoot, "outputs");
  await mkdir(outputDir, { recursive: true });
  await writeFile(
    path.join(outputDir, `${outputBase}.json`),
    JSON.stringify({ runId, total: classified.length, counts, notices: classified }, null, 2),
    "utf8",
  );
  await writeFile(
    path.join(outputDir, `${outputBase}.md`),
    buildMarkdown({ runId, total: classified.length, counts }),
    "utf8",
  );
  await writeFile(
    path.join(outputDir, `${outputBase}.html`),
    buildHtml({ runId, total: classified.length, counts }),
    "utf8",
  );

  console.log(
    JSON.stringify(
      {
        runId,
        total: classified.length,
        outputBase,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
