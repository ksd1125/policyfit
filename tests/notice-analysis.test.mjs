import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyApplicationMethod,
  classifyDocumentProfile,
  classifyPeriodType,
  classifySupportType,
  getExtension,
} from "../scripts/lib/notice-analysis.js";

test("getExtension extracts lowercase extension", () => {
  assert.equal(getExtension("첨부01.HWPX"), ".hwpx");
  assert.equal(getExtension("파일명"), "");
});

test("classifyPeriodType detects date range", () => {
  assert.equal(classifyPeriodType("2025-01-02 ~ 2027-12-31"), "date_range");
});

test("classifyPeriodType detects ongoing and budget-based forms", () => {
  assert.equal(classifyPeriodType("상시 접수"), "always_open");
  assert.equal(classifyPeriodType("예산 소진시까지"), "budget_exhausted");
  assert.equal(classifyPeriodType("추후 공지"), "announced_later");
  assert.equal(classifyPeriodType("세부사업별 상이"), "varies_by_program");
});

test("classifyApplicationMethod detects email-based submission", () => {
  const result = classifyApplicationMethod({
    methodText: "이메일 접수(hgkim@krit.re.kr)",
    homepageUrl: "",
  });
  assert.equal(result.primaryType, "email");
});

test("classifyApplicationMethod detects homepage-based submission", () => {
  const result = classifyApplicationMethod({
    methodText: "온라인 신청",
    homepageUrl: "https://example.org/apply",
  });
  assert.equal(result.primaryType, "website");
});

test("classifyApplicationMethod detects mixed submission channels", () => {
  const result = classifyApplicationMethod({
    methodText: "이메일 또는 방문 접수",
    homepageUrl: "https://example.org/apply",
  });
  assert.equal(result.primaryType, "mixed");
});

test("classifyDocumentProfile detects html plus print only notices", () => {
  const result = classifyDocumentProfile({
    printFileName: "공고문.pdf",
    attachmentFileNames: [],
  });
  assert.equal(result.primaryType, "html_plus_print");
});

test("classifyDocumentProfile detects hwp-core notices", () => {
  const result = classifyDocumentProfile({
    printFileName: "공고문.pdf",
    attachmentFileNames: ["신청서.hwp", "안내문.pdf"],
  });
  assert.equal(result.primaryType, "hwp_core");
});

test("classifyDocumentProfile detects bundle notices", () => {
  const result = classifyDocumentProfile({
    printFileName: "공고문.pdf",
    attachmentFileNames: ["제출양식.zip", "안내문.pdf"],
  });
  assert.equal(result.primaryType, "bundle_package");
});

test("classifySupportType maps subcategory to funding", () => {
  const result = classifySupportType({
    categoryName: "금융",
    subcategoryName: "융자",
    summaryText: "",
  });
  assert.equal(result.primaryType, "funding");
});

test("classifySupportType maps subcategory to consulting", () => {
  const result = classifySupportType({
    categoryName: "경영",
    subcategoryName: "컨설팅",
    summaryText: "",
  });
  assert.equal(result.primaryType, "consulting");
});

test("classifySupportType maps online and promotion style notices to commercialization", () => {
  const result = classifySupportType({
    categoryName: "내수",
    subcategoryName: "온라인",
    summaryText: "온라인 입점과 홍보를 지원",
  });
  assert.equal(result.primaryType, "commercialization");
});
