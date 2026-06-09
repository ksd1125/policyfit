// 기업마당 API에서 최신 공고를 가져와 목적문 테스트용 JSON으로 저장.
// 사용: node scripts/fetch-api-sample.mjs [건수]
import { writeFile } from "node:fs/promises";
import https from "node:https";
import {
  buildApiUrl, loadApiKey, normalizeItemsFromResponse,
} from "./lib/bizinfo.js";

const N = Number(process.argv[2] || 8);
const CATEGORIES = ["02", "03", "04", "05"]; // 금융/내수/창업/경영

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { rejectUnauthorized: false }, (res) => {
      const d = [];
      res.on("data", (c) => d.push(c));
      res.on("end", () => resolve(JSON.parse(Buffer.concat(d).toString("utf8"))));
    }).on("error", reject);
  });
}

// HTML → 평문 (사업개요 텍스트만)
function stripHtml(html) {
  return (html || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

const apiKey = loadApiKey(process.cwd());
const out = [];
for (const cat of CATEGORIES) {
  const url = buildApiUrl({ apiKey, categoryCode: cat, pageIndex: 1, pageUnit: N });
  const payload = await get(url);
  const items = normalizeItemsFromResponse(payload);
  for (const it of items.slice(0, Math.ceil(N / CATEGORIES.length))) {
    out.push({
      id: it.pblancId,
      title: it.pblancNm,
      category: it.pldirSportRealmLclasCodeNm || cat,
      target: it.trgetNm || "",
      summary: stripHtml(it.bsnsSumryCn),  // detail.md 사업개요와 동일 구조
      url: it.pblancUrl,
    });
  }
}

await writeFile("outputs/_api_test.json", JSON.stringify(out, null, 2), "utf8");
console.log(`API에서 ${out.length}건 수신 → outputs/_api_test.json`);
out.forEach((o, i) => console.log(`  [${i + 1}] ${o.title.slice(0, 45)}`));
