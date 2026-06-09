import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

export function getExtension(fileName = "") {
  return path.extname(fileName).toLowerCase();
}

export function splitAttachmentNames(namesText = "") {
  return namesText
    .split("@")
    .map((value) => value.trim())
    .filter(Boolean);
}

export function classifyPeriodType(periodText = "") {
  if (periodText.includes("~")) {
    return "date_range";
  }
  if (periodText.includes("상시")) {
    return "always_open";
  }
  if (periodText.includes("예산 소진")) {
    return "budget_exhausted";
  }
  if (periodText.includes("추후 공지")) {
    return "announced_later";
  }
  if (periodText.includes("세부사업별 상이")) {
    return "varies_by_program";
  }
  return "other";
}

export function classifyApplicationMethod({ methodText = "", homepageUrl = "" }) {
  const text = `${methodText} ${homepageUrl}`.trim();
  const signals = new Set();

  if (/@/.test(methodText)) {
    signals.add("email");
  }
  if (/https?:\/\//.test(text) || homepageUrl) {
    signals.add("website");
  }
  if (/(방문|내방)/.test(methodText)) {
    signals.add("visit");
  }
  if (/(우편)/.test(methodText)) {
    signals.add("post");
  }
  if (/(팩스|fax)/i.test(methodText)) {
    signals.add("fax");
  }

  let primaryType = "other";
  if (signals.size > 1) {
    primaryType = "mixed";
  } else if (signals.size === 1) {
    primaryType = Array.from(signals)[0];
  }

  return {
    primaryType,
    channels: Array.from(signals).sort(),
  };
}

export function classifyDocumentProfile({ printFileName = "", attachmentFileNames = [] }) {
  const attachmentExts = attachmentFileNames.map(getExtension);
  const hasZip = attachmentExts.includes(".zip");
  const hasHwp = attachmentExts.includes(".hwp") || attachmentExts.includes(".hwpx");
  const hasPdf = attachmentExts.includes(".pdf");
  const hasOffice = attachmentExts.some((ext) => [".xlsx", ".pptx", ".docx"].includes(ext));
  const hasImage = attachmentExts.some((ext) => [".png", ".jpg", ".jpeg", ".gif"].includes(ext));
  const hasPrint = Boolean(printFileName);

  let primaryType = "html_only";
  if (attachmentFileNames.length === 0 && hasPrint) {
    primaryType = "html_plus_print";
  } else if (hasZip) {
    primaryType = "bundle_package";
  } else if (hasHwp) {
    primaryType = "hwp_core";
  } else if (hasPdf) {
    primaryType = "pdf_core";
  } else if (attachmentFileNames.length > 0) {
    primaryType = "mixed_attachment";
  }

  const traits = [];
  if (hasPrint) traits.push("has_print_file");
  if (hasHwp) traits.push("has_hwp_family");
  if (hasPdf) traits.push("has_pdf");
  if (hasZip) traits.push("has_zip");
  if (hasOffice) traits.push("has_office_forms");
  if (hasImage) traits.push("has_image_asset");

  return {
    primaryType,
    traits,
    attachmentCount: attachmentFileNames.length,
  };
}

export function classifySupportType({ categoryName = "", subcategoryName = "", summaryText = "" }) {
  const text = `${categoryName} ${subcategoryName} ${summaryText}`;
  let primaryType = "other";

  if (/(융자|보증|보험|펀드|이차보전|자금)/.test(text)) {
    primaryType = "funding";
  } else if (/(컨설팅|자문|멘토링|진단)/.test(text)) {
    primaryType = "consulting";
  } else if (/(예비창업|창업공간|창업정보제공|창업)/.test(subcategoryName)) {
    primaryType = "startup";
  } else if (/(시설|입지|공간|장비)/.test(subcategoryName)) {
    primaryType = "facility";
  } else if (/(교육|세미나|설명회|IR|워크숍)/.test(text)) {
    primaryType = "education_event";
  } else if (/(온라인|오프라인|홍보|공공구매|사업화|상품화|디자인|정보화)/.test(text)) {
    primaryType = "commercialization";
  }

  return {
    primaryType,
  };
}

export function classifyTargetType(targetText = "") {
  if (targetText.includes("소상공인")) return "small_business";
  if (targetText.includes("창업벤처")) return "startup_venture";
  if (targetText.includes("중소기업")) return "sme";
  if (targetText.includes("사회적기업")) return "social_enterprise";
  return "other";
}

export function classifyNotice(item) {
  const attachmentFileNames = splitAttachmentNames(item.fileNm);
  const period = classifyPeriodType(item.reqstBeginEndDe || "");
  const application = classifyApplicationMethod({
    methodText: item.reqstMthPapersCn || "",
    homepageUrl: item.rceptEngnHmpgUrl || "",
  });
  const documentProfile = classifyDocumentProfile({
    printFileName: item.printFileNm || "",
    attachmentFileNames,
  });
  const supportType = classifySupportType({
    categoryName: item.categoryName || item.pldirSportRealmLclasCodeNm || "",
    subcategoryName: item.pldirSportRealmMlsfcCodeNm || "",
    summaryText: item.bsnsSumryCn || "",
  });
  const targetType = classifyTargetType(item.trgetNm || "");

  return {
    noticeId: item.pblancId,
    title: item.pblancNm,
    category: item.categoryName,
    subcategory: item.pldirSportRealmMlsfcCodeNm || "",
    targetText: item.trgetNm || "",
    targetType,
    periodType: period,
    applicationType: application.primaryType,
    applicationChannels: application.channels,
    documentProfile: documentProfile.primaryType,
    documentTraits: documentProfile.traits,
    attachmentCount: documentProfile.attachmentCount,
    supportType: supportType.primaryType,
  };
}

export function countBy(items, key) {
  const counts = {};
  for (const item of items) {
    const value = item[key] || "[empty]";
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

export function sortCountEntries(counts) {
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

export function getLatestRunId(apiRoot) {
  const entries = readdirSync(apiRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^\d{8}-\d{6}$/.test(entry.name))
    .map((entry) => entry.name)
    .sort();
  return entries.at(-1);
}

export function loadItemsForRun(projectRoot, runId) {
  const filePath = path.join(projectRoot, "raw", "api", runId, "all-items.json");
  return JSON.parse(readFileSync(filePath, "utf8"));
}
