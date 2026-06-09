import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAttachmentEntries,
  buildApiUrl,
  CATEGORY_MAP,
  normalizeItemsFromResponse,
  parseDotEnv,
  sanitizeFileName,
  toDownloadUrl,
} from "../scripts/lib/bizinfo.js";

test("parseDotEnv reads BIZINFO_API_KEY from .env.local style text", () => {
  const parsed = parseDotEnv("BIZINFO_API_KEY=test-key-123\n");
  assert.equal(parsed.BIZINFO_API_KEY, "test-key-123");
});

test("buildApiUrl includes official Bizinfo query parameters", () => {
  const url = buildApiUrl({
    apiKey: "secret-key",
    categoryCode: CATEGORY_MAP["\uCC3D\uC5C5"],
    pageIndex: 3,
    pageUnit: 100,
  });

  assert.equal(url.origin + url.pathname, "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do");
  assert.equal(url.searchParams.get("crtfcKey"), "secret-key");
  assert.equal(url.searchParams.get("dataType"), "json");
  assert.equal(url.searchParams.get("searchLclasId"), "06");
  assert.equal(url.searchParams.get("pageUnit"), "100");
  assert.equal(url.searchParams.get("pageIndex"), "3");
});

test("normalizeItemsFromResponse returns jsonArray items when present", () => {
  const items = normalizeItemsFromResponse({
    jsonArray: [{ pblancId: "P1" }, { pblancId: "P2" }],
  });

  assert.deepEqual(items, [{ pblancId: "P1" }, { pblancId: "P2" }]);
});

test("buildAttachmentEntries pairs attachment names and urls", () => {
  const entries = buildAttachmentEntries({
    namesText: "첨부1.hwp@첨부2.pdf",
    urlsText: "https://a.example/file1@https://a.example/file2",
  });

  assert.deepEqual(entries, [
    { fileName: "첨부1.hwp", url: "https://a.example/file1" },
    { fileName: "첨부2.pdf", url: "https://a.example/file2" },
  ]);
});

test("sanitizeFileName removes Windows-forbidden characters", () => {
  assert.equal(
    sanitizeFileName("첨부: 신청서/양식?.hwp"),
    "첨부_ 신청서_양식_.hwp",
  );
});

test("toDownloadUrl converts getImageFile endpoint into fileDown endpoint", () => {
  assert.equal(
    toDownloadUrl("https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?atchFileId=FILE_1&fileSn=0"),
    "https://www.bizinfo.go.kr/cmm/fms/fileDown.do?atchFileId=FILE_1&fileSn=0",
  );
});
