// 기업마당 API에서 소량(기본 5건)을 상세 HTML + 첨부 PDF까지 수집 → raw 구조 저장.
// end-to-end 테스트용. 사용: node scripts/collect-mini.mjs [건수] [runId]
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import https from "node:https";
import {
  buildApiUrl, loadApiKey, normalizeItemsFromResponse,
  buildAttachmentEntries, sanitizeFileName, toDownloadUrl,
} from "./lib/bizinfo.js";

const N = Number(process.argv[2] || 5);
const RUN_ID = process.argv[3] || `e2e-${Date.now()}`;
const ROOT = process.cwd();

function request(url, headers = {}) {
  return new Promise((resolve, reject) => {
    https.get(url, { rejectUnauthorized: false, headers }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ response: res, body: Buffer.concat(chunks) }));
    }).on("error", reject);
  });
}
async function save(fp, text) {
  await mkdir(path.dirname(fp), { recursive: true });
  await writeFile(fp, text, "utf8");
}

const apiKey = loadApiKey(ROOT);
// 금융 카테고리 1페이지에서 N건
const url = buildApiUrl({ apiKey, categoryCode: "02", pageIndex: 1, pageUnit: N });
const payload = await request(url).then((r) => JSON.parse(r.body.toString("utf8")));
const items = normalizeItemsFromResponse(payload).slice(0, N);

// 1) all-items.json (normalize가 기대하는 형식)
const allItems = items.map((it) => ({
  ...it,
  categoryName: "금융",
  categoryCode: "02",
  inDateWindow: true,
}));
await save(path.join(ROOT, "raw", "api", RUN_ID, "all-items.json"),
           JSON.stringify(allItems, null, 2));

async function saveBuf(fp, buf) {
  await mkdir(path.dirname(fp), { recursive: true });
  await writeFile(fp, buf);
}

// 2) 각 공고 상세 HTML 크롤링 → 쿠키 받아 첨부 다운로드
let htmlSaved = 0, fileSaved = 0;
for (const it of items) {
  if (!it.pblancUrl) continue;
  let detailHeaders = {};
  try {
    const { response, body } = await request(it.pblancUrl);
    await save(path.join(ROOT, "raw", "html", RUN_ID, `${it.pblancId}.html`),
               body.toString("utf8"));
    htmlSaved++;
    // 첨부 다운로드용 쿠키/Referer 헤더 추출
    const cookies = (response.headers["set-cookie"] || [])
      .map((v) => v.split(";")[0]).join("; ");
    detailHeaders = cookies
      ? { Cookie: cookies, Referer: it.pblancUrl, "User-Agent": "Mozilla/5.0" }
      : { Referer: it.pblancUrl, "User-Agent": "Mozilla/5.0" };
  } catch (e) {
    console.error(`  HTML 실패: ${it.pblancId} ${e.message}`);
    continue;
  }

  // 3) 첨부 PDF/HWP 등 다운로드 → raw/files/{runId}/{id}/
  const attachments = buildAttachmentEntries({
    namesText: it.fileNm, urlsText: it.flpthNm,
  });
  const noticeDir = path.join(ROOT, "raw", "files", RUN_ID, it.pblancId);
  await mkdir(noticeDir, { recursive: true });
  for (const [idx, att] of attachments.entries()) {
    try {
      const { body } = await request(toDownloadUrl(att.url), detailHeaders);
      const fn = sanitizeFileName(att.fileName);
      await saveBuf(path.join(noticeDir, `${String(idx + 1).padStart(2, "0")}__${fn}`), body);
      fileSaved++;
    } catch (e) {
      console.error(`  첨부 실패: ${it.pblancId}#${idx + 1} ${e.message}`);
    }
  }
}

console.log(`runId=${RUN_ID}`);
console.log(`API ${items.length}건 → all-items.json, 상세 HTML ${htmlSaved}건, 첨부 ${fileSaved}개 저장`);
items.forEach((it, i) => console.log(`  [${i + 1}] ${it.pblancNm.slice(0, 45)}`));
