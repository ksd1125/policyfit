"""공고 정규화 파이프라인

3개 소스(API 메타데이터, 상세 HTML MD, 첨부 MD)에서 8개 필드를 추출하고
우선순위에 따라 병합하여 챗봇용 정규화 데이터셋을 생성한다.

우선순위: API 구조화 필드 > HTML 구조화 섹션 > 첨부 키워드 추출
각 필드에 source(출처)와 confidence(신뢰도) 메타데이터를 부여한다.
"""

import json
import os
import re
import sys
from html import unescape
from pathlib import Path
from collections import Counter


def find_latest_run_id(raw_dir):
    api_dir = raw_dir / "api"
    runs = sorted(
        [d.name for d in api_dir.iterdir() if d.is_dir() and re.match(r"\d{8}-\d{6}", d.name)],
        reverse=True,
    )
    return runs[0] if runs else None


def clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"&\w+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_html_section(md_text, headers):
    for header in headers:
        pattern = rf"## {re.escape(header)}\n\n(.*?)(?=\n## |\n---|\Z)"
        match = re.search(pattern, md_text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def extract_attach_snippet(texts, patterns, context_lines=5):
    for text in texts:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            for pattern in patterns:
                if re.search(pattern, line):
                    start = max(0, i)
                    end = min(len(lines), i + context_lines)
                    snippet = "\n".join(lines[start:end]).strip()
                    if len(snippet) > 10:
                        return snippet
    return None


FIELD_CONFIGS = {
    "지원대상": {
        "api_key": "trgetNm",
        "html_headers": ["지원대상", "신청자격", "참여자격", "모집대상", "지원 대상"],
        "attach_patterns": [r"지원\s*대상", r"신청\s*자격", r"참여\s*자격", r"모집\s*대상"],
    },
    "지원내용": {
        "api_key": "bsnsSumryCn",
        "html_headers": ["사업개요", "지원내용", "사업내용", "지원 내용"],
        "attach_patterns": [r"지원\s*내용", r"사업\s*내용", r"지원\s*규모"],
    },
    "신청기간": {
        "api_key": "reqstBeginEndDe",
        "html_headers": ["신청기간", "접수기간", "모집기간", "신청 기간"],
        "attach_patterns": [r"신청\s*기간", r"접수\s*기간", r"모집\s*기간"],
    },
    "신청방법": {
        "api_key": "reqstMthPapersCn",
        "html_headers": ["사업신청 방법", "신청방법", "접수방법", "신청 방법"],
        "attach_patterns": [r"신청\s*방법", r"접수\s*방법", r"제출\s*방법"],
    },
    "제출서류": {
        "api_key": None,
        "html_headers": ["제출서류", "구비서류", "필요서류"],
        "attach_patterns": [r"제출\s*서류", r"구비\s*서류", r"필요\s*서류", r"신청\s*서류"],
    },
    "제외조건": {
        "api_key": None,
        "html_headers": ["제외조건", "지원제외", "신청제외"],
        "attach_patterns": [r"제외\s*조건", r"지원\s*제외", r"참여\s*제한", r"지원\s*제한", r"제외\s*대상"],
    },
    "문의처": {
        "api_key": "refrncNm",
        "html_headers": ["문의처", "문의", "담당자", "연락처"],
        "attach_patterns": [r"문의\s*처", r"담당\s*자", r"연락\s*처"],
    },
    "유의사항": {
        "api_key": None,
        "html_headers": ["유의사항", "참고사항", "기타사항"],
        "attach_patterns": [r"유의\s*사항", r"참고\s*사항", r"기타\s*사항", r"주의\s*사항"],
    },
}


def extract_field(item, detail_md, attach_texts, config):
    # 1) API
    if config["api_key"]:
        val = str(item.get(config["api_key"], "")).strip()
        if len(val) > 2:
            return {"value": clean_html(val), "source": "api", "confidence": "high"}

    # 2) HTML
    if detail_md:
        val = extract_html_section(detail_md, config["html_headers"])
        if val and len(val) > 5:
            return {"value": val, "source": "html", "confidence": "high"}

    # 3) 첨부
    if attach_texts:
        val = extract_attach_snippet(attach_texts, config["attach_patterns"])
        if val:
            return {"value": val, "source": "attachment", "confidence": "medium"}

    return {"value": None, "source": None, "confidence": "missing"}


def build_normalized_notice(item, detail_md, attach_texts):
    notice = {
        "id": item["pblancId"],
        "title": item.get("pblancNm", ""),
        "category": item.get("categoryName", ""),
        "subcategory": item.get("pldirSportRealmMlsfcCodeNm", ""),
        "institution": item.get("jrsdInsttNm", ""),
        "executor": item.get("excInsttNm", ""),
        "registeredAt": item.get("creatPnttm", ""),
        "url": item.get("pblancUrl", ""),
        "hashtags": str(item.get("hashtags", "")),
        "fields": {},
    }

    for field_name, config in FIELD_CONFIGS.items():
        notice["fields"][field_name] = extract_field(item, detail_md, attach_texts, config)

    return notice


def main():
    project_root = Path.cwd()
    raw_dir = project_root / "raw"
    run_id = os.environ.get("E2E_RUN_ID") or find_latest_run_id(raw_dir)
    print(f"Run ID: {run_id}")

    items = json.loads((raw_dir / "api" / run_id / "all-items.json").read_text(encoding="utf-8"))
    items_by_id = {item["pblancId"]: item for item in items}
    md_dir = raw_dir / "markdown" / run_id

    normalized = []
    stats = Counter()

    notice_dirs = sorted(md_dir.iterdir()) if md_dir.exists() else []
    total = len(notice_dirs)
    print(f"Notices: {total}")

    for i, notice_dir in enumerate(notice_dirs):
        if not notice_dir.is_dir():
            continue
        notice_id = notice_dir.name
        item = items_by_id.get(notice_id, {})

        detail_md = ""
        detail_path = notice_dir / "detail.md"
        if detail_path.exists():
            detail_md = detail_path.read_text(encoding="utf-8", errors="replace")

        attach_texts = []
        for f in sorted(notice_dir.iterdir()):
            if f.is_file() and f.name != "detail.md" and f.suffix == ".md":
                attach_texts.append(f.read_text(encoding="utf-8", errors="replace"))

        notice = build_normalized_notice(item, detail_md, attach_texts)
        normalized.append(notice)

        for field_name, field_data in notice["fields"].items():
            if field_data["value"]:
                stats[f"{field_name}:{field_data['source']}"] += 1
            else:
                stats[f"{field_name}:missing"] += 1

        if (i + 1) % 200 == 0:
            print(f"  Processed: {i + 1}/{total}")

    print(f"  Processed: {total}/{total}")

    # 저장
    outputs_dir = project_root / "outputs"
    dataset_path = outputs_dir / f"normalized-notices-{run_id}.json"
    dataset_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 통계 요약
    summary_lines = [
        f"# 정규화 데이터셋 생성 결과\n",
        f"- runId: {run_id}",
        f"- 공고 수: {total}건",
        f"- 데이터셋: {dataset_path.name} ({dataset_path.stat().st_size // 1024}KB)\n",
        "## 필드별 추출 소스 분포\n",
        "| 필드 | API | HTML | 첨부 | 미추출 |",
        "|------|-----|------|------|--------|",
    ]

    for field_name in FIELD_CONFIGS:
        api = stats.get(f"{field_name}:api", 0)
        html = stats.get(f"{field_name}:html", 0)
        attach = stats.get(f"{field_name}:attachment", 0)
        missing = stats.get(f"{field_name}:missing", 0)
        summary_lines.append(f"| {field_name} | {api} | {html} | {attach} | {missing} |")

    summary_lines.append(f"\n## 신뢰도 분포\n")
    high = sum(1 for n in normalized for f in n["fields"].values() if f["confidence"] == "high")
    medium = sum(1 for n in normalized for f in n["fields"].values() if f["confidence"] == "medium")
    missing = sum(1 for n in normalized for f in n["fields"].values() if f["confidence"] == "missing")
    total_fields = high + medium + missing
    summary_lines.append(f"- high (API/HTML 구조화): {high}건 ({high/total_fields*100:.1f}%)")
    summary_lines.append(f"- medium (첨부 키워드): {medium}건 ({medium/total_fields*100:.1f}%)")
    summary_lines.append(f"- missing (미추출): {missing}건 ({missing/total_fields*100:.1f}%)")

    md_path = outputs_dir / f"normalized-summary-{run_id}.md"
    md_path.write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"\nSaved: {dataset_path.name} ({dataset_path.stat().st_size // 1024}KB)")
    print(f"Saved: {md_path.name}")
    print(json.dumps({"total": total, "datasetKB": dataset_path.stat().st_size // 1024}, indent=2))


if __name__ == "__main__":
    main()
