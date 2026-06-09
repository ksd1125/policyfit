"""정규화 후보 필드 추출 가능성 분석

3개 소스에서 8개 타겟 필드의 커버리지를 측정한다:
  1) API 메타데이터 (구조화된 필드)
  2) 상세 HTML → MD (구조화된 섹션 헤더)
  3) 첨부파일 → MD (키워드 패턴 검색)

분류 기준:
  - always: 90%+ 커버리지
  - partial: 30~90% 커버리지
  - attachment_only: HTML에서 30% 미만이지만 첨부에서 30%+ 추가 발견
  - rare: 전체 30% 미만
"""

import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict


TARGET_FIELDS = {
    "지원대상": {
        "api_key": "trgetNm",
        "html_headers": ["지원대상", "신청자격", "참여자격", "모집대상", "지원 대상"],
        "attach_patterns": [
            r"지원\s*대상", r"신청\s*자격", r"참여\s*자격", r"모집\s*대상",
            r"사업\s*대상", r"지원\s*자격",
        ],
    },
    "지원내용": {
        "api_key": "bsnsSumryCn",
        "html_headers": ["사업개요", "지원내용", "사업내용", "지원 내용"],
        "attach_patterns": [
            r"지원\s*내용", r"사업\s*내용", r"지원\s*규모", r"지원\s*사항",
            r"지원\s*범위", r"보조금", r"지원금",
        ],
    },
    "신청기간": {
        "api_key": "reqstBeginEndDe",
        "html_headers": ["신청기간", "접수기간", "모집기간", "신청 기간"],
        "attach_patterns": [
            r"신청\s*기간", r"접수\s*기간", r"모집\s*기간", r"공모\s*기간",
            r"신청\s*일시", r"접수\s*일정",
        ],
    },
    "신청방법": {
        "api_key": "reqstMthPapersCn",
        "html_headers": ["사업신청 방법", "신청방법", "접수방법", "신청 방법"],
        "attach_patterns": [
            r"신청\s*방법", r"접수\s*방법", r"제출\s*방법", r"신청\s*절차",
            r"접수\s*절차", r"온라인\s*접수", r"이메일\s*접수",
        ],
    },
    "제출서류": {
        "api_key": None,
        "html_headers": ["제출서류", "구비서류", "필요서류", "제출 서류"],
        "attach_patterns": [
            r"제출\s*서류", r"구비\s*서류", r"필요\s*서류", r"신청\s*서류",
            r"첨부\s*서류", r"제출.*서식",
        ],
    },
    "제외조건": {
        "api_key": None,
        "html_headers": ["제외조건", "지원제외", "신청제외", "제외 대상"],
        "attach_patterns": [
            r"제외\s*조건", r"지원\s*제외", r"신청\s*제외", r"제외\s*대상",
            r"참여\s*제한", r"지원\s*제한", r"중복\s*지원.*제한",
            r"지원.*불가", r"제외.*대상",
        ],
    },
    "문의처": {
        "api_key": "refrncNm",
        "html_headers": ["문의처", "문의", "담당자", "연락처"],
        "attach_patterns": [
            r"문의\s*처", r"문의\s*:", r"담당\s*자", r"연락\s*처",
            r"전화\s*:", r"☎", r"TEL\s*:",
        ],
    },
    "유의사항": {
        "api_key": None,
        "html_headers": ["유의사항", "참고사항", "기타사항", "유의 사항"],
        "attach_patterns": [
            r"유의\s*사항", r"참고\s*사항", r"기타\s*사항", r"주의\s*사항",
            r"※\s*유의", r"※\s*참고", r"lull.*유의",
        ],
    },
}


def check_api_field(item, field_config):
    key = field_config["api_key"]
    if not key:
        return False
    val = str(item.get(key, "")).strip()
    return len(val) > 2


def check_html_md(md_text, field_config):
    for header in field_config["html_headers"]:
        if f"## {header}" in md_text:
            return True
    return False


def check_attachment_text(texts, field_config):
    for text in texts:
        for pattern in field_config["attach_patterns"]:
            if re.search(pattern, text):
                return True
    return False


def main():
    project_root = Path.cwd()
    raw_dir = project_root / "raw"

    api_dir = raw_dir / "api"
    runs = sorted([d.name for d in api_dir.iterdir() if d.is_dir() and re.match(r"\d{8}-\d{6}", d.name)], reverse=True)
    run_id = runs[0]
    print(f"Run ID: {run_id}")

    items = json.loads((api_dir / run_id / "all-items.json").read_text(encoding="utf-8"))
    items_by_id = {item["pblancId"]: item for item in items}

    md_dir = raw_dir / "markdown" / run_id

    per_notice = defaultdict(lambda: defaultdict(dict))
    field_stats = defaultdict(lambda: {"api": 0, "html": 0, "attach": 0, "any": 0, "html_or_api": 0})

    notice_dirs = sorted(md_dir.iterdir()) if md_dir.exists() else []
    total = len(notice_dirs)
    print(f"Notices to analyze: {total}")

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
        for f in notice_dir.iterdir():
            if f.is_file() and f.name != "detail.md" and f.suffix == ".md":
                attach_texts.append(f.read_text(encoding="utf-8", errors="replace"))

        for field_name, config in TARGET_FIELDS.items():
            has_api = check_api_field(item, config)
            has_html = check_html_md(detail_md, config)
            has_attach = check_attachment_text(attach_texts, config)

            per_notice[notice_id][field_name] = {
                "api": has_api, "html": has_html, "attach": has_attach,
            }

            if has_api:
                field_stats[field_name]["api"] += 1
            if has_html:
                field_stats[field_name]["html"] += 1
            if has_attach:
                field_stats[field_name]["attach"] += 1
            if has_api or has_html or has_attach:
                field_stats[field_name]["any"] += 1
            if has_api or has_html:
                field_stats[field_name]["html_or_api"] += 1

        if (i + 1) % 200 == 0:
            print(f"  Analyzed: {i + 1}/{total}")

    print(f"  Analyzed: {total}/{total}\n")

    # 분류
    classifications = {}
    for field_name in TARGET_FIELDS:
        stats = field_stats[field_name]
        api_pct = stats["api"] / total * 100
        html_pct = stats["html"] / total * 100
        struct_pct = stats["html_or_api"] / total * 100
        attach_pct = stats["attach"] / total * 100
        any_pct = stats["any"] / total * 100

        if struct_pct >= 90:
            grade = "always"
        elif struct_pct >= 30:
            grade = "partial"
        elif attach_pct >= 30:
            grade = "attachment_only"
        else:
            grade = "rare"

        classifications[field_name] = {
            "grade": grade,
            "api": stats["api"], "api_pct": round(api_pct, 1),
            "html": stats["html"], "html_pct": round(html_pct, 1),
            "attach": stats["attach"], "attach_pct": round(attach_pct, 1),
            "any": stats["any"], "any_pct": round(any_pct, 1),
            "struct": stats["html_or_api"], "struct_pct": round(struct_pct, 1),
        }

    # 콘솔 출력
    print(f"{'필드':8s} | {'등급':16s} | {'API':>8s} | {'HTML':>8s} | {'구조합':>8s} | {'첨부':>8s} | {'전체':>8s}")
    print("-" * 85)
    for field_name, c in classifications.items():
        print(f"{field_name:8s} | {c['grade']:16s} | {c['api_pct']:>7.1f}% | {c['html_pct']:>7.1f}% | {c['struct_pct']:>7.1f}% | {c['attach_pct']:>7.1f}% | {c['any_pct']:>7.1f}%")

    # JSON 저장
    outputs_dir = project_root / "outputs"
    result = {
        "runId": run_id,
        "totalNotices": total,
        "classifications": classifications,
    }
    json_path = outputs_dir / f"field-coverage-{run_id}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # MD 저장
    md_lines = [
        f"# 정규화 후보 필드 커버리지 분석\n",
        f"- runId: {run_id}",
        f"- 분석 공고 수: {total}건\n",
        "## 분류 기준\n",
        "- **always**: 구조화 소스(API+HTML)에서 90%+ 커버리지",
        "- **partial**: 구조화 소스에서 30~90% 커버리지",
        "- **attachment_only**: 구조화 소스 30% 미만, 첨부에서 30%+ 추가 발견",
        "- **rare**: 전체 30% 미만\n",
        "## 필드별 결과\n",
        "| 필드 | 등급 | API | HTML | 구조합 | 첨부 | 전체 |",
        "|------|------|-----|------|--------|------|------|",
    ]
    for field_name, c in classifications.items():
        md_lines.append(
            f"| {field_name} | {c['grade']} | {c['api_pct']}% | {c['html_pct']}% | {c['struct_pct']}% | {c['attach_pct']}% | {c['any_pct']}% |"
        )

    md_lines.append("\n## 해석\n")

    always_fields = [f for f, c in classifications.items() if c["grade"] == "always"]
    partial_fields = [f for f, c in classifications.items() if c["grade"] == "partial"]
    attach_fields = [f for f, c in classifications.items() if c["grade"] == "attachment_only"]
    rare_fields = [f for f, c in classifications.items() if c["grade"] == "rare"]

    if always_fields:
        md_lines.append(f"### 안정 추출 (always)\n")
        md_lines.append(f"API 또는 HTML에서 항상 확보: {', '.join(always_fields)}\n")
    if partial_fields:
        md_lines.append(f"### 부분 추출 (partial)\n")
        md_lines.append(f"구조화 소스에서 부분 확보, 첨부 보강 가능: {', '.join(partial_fields)}\n")
    if attach_fields:
        md_lines.append(f"### 첨부 의존 (attachment_only)\n")
        md_lines.append(f"구조화 소스에서 희박, 첨부파일 파싱 필수: {', '.join(attach_fields)}\n")
    if rare_fields:
        md_lines.append(f"### 희귀 (rare)\n")
        md_lines.append(f"전체적으로 추출 어려움: {', '.join(rare_fields)}\n")

    md_path = outputs_dir / f"field-coverage-{run_id}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nSaved: {json_path.name}, {md_path.name}")


if __name__ == "__main__":
    main()
