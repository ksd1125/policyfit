import { readFileSync } from "node:fs";
import path from "node:path";

export const CATEGORY_MAP = {
  "\uAE08\uC735": "01",
  "\uB0B4\uC218": "05",
  "\uCC3D\uC5C5": "06",
  "\uACBD\uC601": "07",
};

export function parseDotEnv(content) {
  const result = {};
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex < 0) {
      continue;
    }
    const key = trimmed.slice(0, separatorIndex).trim();
    const value = trimmed.slice(separatorIndex + 1).trim();
    result[key] = value;
  }
  return result;
}

export function loadApiKey(projectRoot) {
  const envPath = path.join(projectRoot, ".env.local");
  const parsed = parseDotEnv(readFileSync(envPath, "utf8"));
  const apiKey = parsed.BIZINFO_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("BIZINFO_API_KEY is missing in .env.local");
  }
  return apiKey;
}

export function buildApiUrl({ apiKey, categoryCode, pageIndex, pageUnit = 100 }) {
  const url = new URL("https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do");
  url.searchParams.set("crtfcKey", apiKey);
  url.searchParams.set("dataType", "json");
  url.searchParams.set("searchLclasId", categoryCode);
  url.searchParams.set("pageUnit", String(pageUnit));
  url.searchParams.set("pageIndex", String(pageIndex));
  return url;
}

export function normalizeItemsFromResponse(payload) {
  const items = payload?.jsonArray ?? payload?.items ?? [];
  if (!Array.isArray(items)) {
    return [];
  }
  return items;
}

export function sanitizeFileName(fileName) {
  return fileName.replace(/[<>:"/\\|?*]/g, "_");
}

export function buildAttachmentEntries({ namesText = "", urlsText = "" }) {
  const names = namesText
    .split("@")
    .map((value) => value.trim())
    .filter(Boolean);
  const urls = urlsText
    .split("@")
    .map((value) => value.trim())
    .filter(Boolean);

  return urls.map((url, index) => ({
    fileName: names[index] || `attachment-${String(index + 1).padStart(2, "0")}`,
    url,
  }));
}

export function toDownloadUrl(url) {
  return url.replace("/getImageFile.do", "/fileDown.do");
}
