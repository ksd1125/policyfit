import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import https from "node:https";

import {
  buildApiUrl,
  buildAttachmentEntries,
  CATEGORY_MAP,
  loadApiKey,
  normalizeItemsFromResponse,
  sanitizeFileName,
  toDownloadUrl,
} from "./lib/bizinfo.js";

const START_DATE = "2024-06-01";
const END_DATE = "2026-06-01";
const PAGE_UNIT = 100;

function timestampForFolder(date = new Date()) {
  const yyyy = String(date.getFullYear());
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${yyyy}${mm}${dd}-${hh}${mi}${ss}`;
}

function request(url, headers = {}) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { rejectUnauthorized: false, headers }, (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          resolve({ response, body: Buffer.concat(chunks) });
        });
      })
      .on("error", reject);
  });
}

async function requestJson(url) {
  const { response, body } = await request(url);
  if (response.statusCode && response.statusCode >= 400) {
    throw new Error(`HTTP ${response.statusCode} for ${url}`);
  }
  return JSON.parse(body.toString("utf8"));
}

function parseDate(text) {
  if (!text) {
    return null;
  }
  const normalized = text.slice(0, 10);
  const value = new Date(`${normalized}T00:00:00+09:00`);
  return Number.isNaN(value.getTime()) ? null : value;
}

function inWindow(item) {
  const created = parseDate(item.creatPnttm);
  if (!created) {
    return false;
  }
  return created >= new Date(`${START_DATE}T00:00:00+09:00`) && created <= new Date(`${END_DATE}T23:59:59+09:00`);
}

function buildSummaryHtml(summary) {
  const rows = summary.categories
    .map(
      (category) => `
        <tr>
          <td>${category.name}</td>
          <td>${category.code}</td>
          <td>${category.totalItems}</td>
          <td>${category.filteredItems}</td>
          <td>${category.pages}</td>
        </tr>`,
    )
    .join("");

  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Bizinfo Collection Summary</title>
  <style>
    body { font-family: "Malgun Gothic", sans-serif; margin: 24px; color: #222; }
    h1, h2 { margin: 0 0 12px; }
    p { margin: 8px 0; }
    table { border-collapse: collapse; width: 100%; margin-top: 16px; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background: #f3f6fb; }
    code { background: #f4f4f4; padding: 2px 4px; }
  </style>
</head>
<body>
  <h1>기업마당 수집 요약</h1>
  <p>수집시각: ${summary.runId}</p>
  <p>기간 기준: ${summary.window.start} ~ ${summary.window.end}</p>
  <p>전체 원본 공고 수: ${summary.totalItems}</p>
  <p>기간 내 공고 수: ${summary.filteredItems}</p>
  <p>상세 HTML 저장 수: ${summary.detailHtmlSaved}</p>
  <p>첨부/출력파일 저장 수: ${summary.fileSaved}</p>
  <p>실패 기록 수: ${summary.failures.length}</p>
  <h2>분야별 현황</h2>
  <table>
    <thead>
      <tr>
        <th>분야</th>
        <th>코드</th>
        <th>원본 공고 수</th>
        <th>기간 내 공고 수</th>
        <th>페이지 수</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
  <h2>주요 파일</h2>
  <p><code>raw/api/${summary.runId}/</code> API 원본</p>
  <p><code>raw/html/${summary.runId}/</code> 상세 HTML</p>
  <p><code>raw/files/${summary.runId}/</code> 첨부 원문</p>
  <p><code>outputs/${summary.runId}-collection-summary.md</code> 요약 MD</p>
</body>
</html>`;
}

function buildSummaryMarkdown(summary) {
  const categoryLines = summary.categories
    .map(
      (category) =>
        `- ${category.name}(${category.code}): 원본 ${category.totalItems}건 / 기간 내 ${category.filteredItems}건 / ${category.pages}페이지`,
    )
    .join("\n");

  const failureLines =
    summary.failures.length > 0
      ? summary.failures
          .slice(0, 50)
          .map((failure) => `- ${failure.stage}: ${failure.id} / ${failure.message}`)
          .join("\n")
      : "- 없음";

  return `# 기업마당 수집 요약

- 수집시각: ${summary.runId}
- 기간 기준: ${summary.window.start} ~ ${summary.window.end}
- 전체 원본 공고 수: ${summary.totalItems}
- 기간 내 공고 수: ${summary.filteredItems}
- 상세 HTML 저장 수: ${summary.detailHtmlSaved}
- 첨부/출력파일 저장 수: ${summary.fileSaved}
- 실패 기록 수: ${summary.failures.length}

## 분야별 현황
${categoryLines}

## 실패 기록 일부
${failureLines}
`;
}

async function ensureDir(dirPath) {
  await mkdir(dirPath, { recursive: true });
}

async function saveText(filePath, text) {
  await ensureDir(path.dirname(filePath));
  await writeFile(filePath, text, "utf8");
}

async function saveBuffer(filePath, buffer) {
  await ensureDir(path.dirname(filePath));
  await writeFile(filePath, buffer);
}

async function downloadSource(url, filePath, failures, failureId, stage, headers = {}) {
  try {
    const { response, body } = await request(url, headers);
    if (response.statusCode && response.statusCode >= 400) {
      throw new Error(`HTTP ${response.statusCode} for ${url}`);
    }
    await saveBuffer(filePath, body);
    return true;
  } catch (error) {
    failures.push({
      stage,
      id: failureId,
      message: error instanceof Error ? error.message : String(error),
    });
    return false;
  }
}

async function main() {
  const projectRoot = process.cwd();
  const apiKey = loadApiKey(projectRoot);
  const runId = timestampForFolder();

  const apiRunDir = path.join(projectRoot, "raw", "api", runId);
  const htmlRunDir = path.join(projectRoot, "raw", "html", runId);
  const filesRunDir = path.join(projectRoot, "raw", "files", runId);
  await ensureDir(apiRunDir);
  await ensureDir(htmlRunDir);
  await ensureDir(filesRunDir);

  const failures = [];
  const categorySummaries = [];
  const uniqueItems = new Map();

  for (const [categoryName, categoryCode] of Object.entries(CATEGORY_MAP)) {
    const categoryDir = path.join(apiRunDir, categoryName);
    await ensureDir(categoryDir);

    let pageIndex = 1;
    let pages = 0;
    let categoryItems = [];

    while (true) {
      const url = buildApiUrl({ apiKey, categoryCode, pageIndex, pageUnit: PAGE_UNIT });
      const payload = await requestJson(url);
      const items = normalizeItemsFromResponse(payload);

      if (items.length === 0) {
        break;
      }

      pages += 1;
      categoryItems = categoryItems.concat(items);

      const pagePath = path.join(categoryDir, `page-${String(pageIndex).padStart(4, "0")}.json`);
      await saveText(pagePath, JSON.stringify(payload, null, 2));

      if (items.length < PAGE_UNIT) {
        break;
      }
      pageIndex += 1;
    }

    for (const item of categoryItems) {
      uniqueItems.set(item.pblancId, {
        ...item,
        categoryName,
        categoryCode,
        inDateWindow: inWindow(item),
      });
    }

    categorySummaries.push({
      name: categoryName,
      code: categoryCode,
      totalItems: categoryItems.length,
      filteredItems: categoryItems.filter(inWindow).length,
      pages,
    });
  }

  let detailHtmlSaved = 0;
  let fileSaved = 0;

  for (const item of uniqueItems.values()) {
    const noticeId = item.pblancId;
    const noticeDir = path.join(filesRunDir, noticeId);
    await ensureDir(noticeDir);

    let detailHeaders = {};
    if (item.pblancUrl) {
      try {
        const { response, body } = await request(item.pblancUrl);
        if (response.statusCode && response.statusCode >= 400) {
          throw new Error(`HTTP ${response.statusCode} for ${item.pblancUrl}`);
        }
        const htmlPath = path.join(htmlRunDir, `${noticeId}.html`);
        await saveBuffer(htmlPath, body);
        detailHtmlSaved += 1;

        const cookies = (response.headers["set-cookie"] || [])
          .map((value) => value.split(";")[0])
          .join("; ");
        detailHeaders = cookies
          ? {
              Cookie: cookies,
              Referer: item.pblancUrl,
              "User-Agent": "Mozilla/5.0",
            }
          : {
              Referer: item.pblancUrl,
              "User-Agent": "Mozilla/5.0",
            };
      } catch (error) {
        failures.push({
          stage: "detail-html",
          id: noticeId,
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (item.printFlpthNm) {
      const printName = sanitizeFileName(item.printFileNm || `${noticeId}-print-file`);
      const printPath = path.join(noticeDir, `print__${printName}`);
      const ok = await downloadSource(
        toDownloadUrl(item.printFlpthNm),
        printPath,
        failures,
        noticeId,
        "print-file",
        detailHeaders,
      );
      if (ok) {
        fileSaved += 1;
      }
    }

    const attachments = buildAttachmentEntries({
      namesText: item.fileNm,
      urlsText: item.flpthNm,
    });

    for (const [index, attachment] of attachments.entries()) {
      const fileName = sanitizeFileName(attachment.fileName);
      const filePath = path.join(noticeDir, `${String(index + 1).padStart(2, "0")}__${fileName}`);
      const ok = await downloadSource(
        toDownloadUrl(attachment.url),
        filePath,
        failures,
        `${noticeId}#${index + 1}`,
        "attachment-file",
        detailHeaders,
      );
      if (ok) {
        fileSaved += 1;
      }
    }
  }

  const manifest = Array.from(uniqueItems.values()).sort((a, b) => a.pblancId.localeCompare(b.pblancId));
  const filteredManifest = manifest.filter((item) => item.inDateWindow);

  await saveText(path.join(apiRunDir, "all-items.json"), JSON.stringify(manifest, null, 2));
  await saveText(path.join(apiRunDir, "filtered-items-2024-06-01-to-2026-06-01.json"), JSON.stringify(filteredManifest, null, 2));
  await saveText(path.join(apiRunDir, "failures.json"), JSON.stringify(failures, null, 2));

  const summary = {
    runId,
    window: { start: START_DATE, end: END_DATE },
    totalItems: manifest.length,
    filteredItems: filteredManifest.length,
    detailHtmlSaved,
    fileSaved,
    categories: categorySummaries,
    failures,
  };

  await saveText(
    path.join(projectRoot, "outputs", `${runId}-collection-summary.md`),
    buildSummaryMarkdown(summary),
  );
  await saveText(
    path.join(projectRoot, "outputs", "index.html"),
    buildSummaryHtml(summary),
  );
  await saveText(
    path.join(projectRoot, "wiki", "log.md"),
    `# 작업 로그\n\n- ${runId}: 기업마당 4개 분야 수집 실행\n`,
  );

  console.log(
    JSON.stringify(
      {
        runId,
        totalItems: manifest.length,
        filteredItems: filteredManifest.length,
        detailHtmlSaved,
        fileSaved,
        failureCount: failures.length,
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
