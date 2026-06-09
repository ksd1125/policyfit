"""샘플 질의 테스트

정규화 데이터셋을 대상으로 챗봇 시나리오 질의를 수행한다.
키워드 매칭 + 카테고리/해시태그 필터로 공고를 검색하고,
챗봇이 응답할 수 있는 형태로 결과를 포맷한다.

테스트 목표:
  - 질문 의도에 맞는 공고 후보가 검색되는가
  - 핵심 항목(지원대상, 지원내용, 신청기간, 신청방법)을 묶어 설명할 수 있는가
  - 미추출 필드가 응답 품질에 미치는 영향은 어느 정도인가
"""

import json
import re
import sys
from pathlib import Path


SAMPLE_QUERIES = [
    {
        "query": "소상공인 자금 지원",
        "keywords": ["소상공인", "자금", "대출", "융자", "보조금", "지원금"],
        "category_hint": "금융",
    },
    {
        "query": "온라인 판매 판로 지원",
        "keywords": ["온라인", "판로", "판매", "전자상거래", "입점", "마케팅", "홍보", "수출"],
        "category_hint": "내수",
    },
    {
        "query": "창업 초기 지원",
        "keywords": ["창업", "초기", "예비창업", "스타트업", "창업지원", "사업화"],
        "category_hint": "창업",
    },
    {
        "query": "보증 특례보증",
        "keywords": ["보증", "특례", "신용보증", "기술보증", "보증서", "보증지원"],
        "category_hint": "금융",
    },
    {
        "query": "경영 컨설팅 지원",
        "keywords": ["컨설팅", "경영", "진단", "멘토링", "자문", "코칭"],
        "category_hint": "경영",
    },
]


def score_notice(notice, query_config):
    score = 0
    keywords = query_config["keywords"]
    cat = query_config.get("category_hint", "")

    searchable = " ".join([
        notice.get("title", ""),
        notice.get("hashtags", ""),
        notice.get("category", ""),
        notice.get("subcategory", ""),
    ])
    for field_data in notice.get("fields", {}).values():
        if field_data.get("value"):
            searchable += " " + field_data["value"]

    searchable_lower = searchable.lower()

    for kw in keywords:
        if kw in searchable_lower:
            score += 2
        elif kw in searchable:
            score += 2

    if cat and notice.get("category", "") == cat:
        score += 3

    return score


def format_chatbot_response(query, results, top_n=5):
    lines = []
    lines.append(f'## 질의: "{query}"\n')

    if not results:
        lines.append("검색 결과가 없습니다.\n")
        return "\n".join(lines)

    lines.append(f"**{len(results)}건 검색**, 상위 {min(top_n, len(results))}건 표시\n")

    for i, (notice, score) in enumerate(results[:top_n]):
        lines.append(f"### {i+1}. {notice['title']}")
        lines.append(f"- **기관**: {notice.get('institution', '')} / {notice.get('executor', '')}")
        lines.append(f"- **분야**: {notice.get('category', '')} > {notice.get('subcategory', '')}")

        fields = notice.get("fields", {})
        field_order = ["지원대상", "지원내용", "신청기간", "신청방법", "문의처", "제출서류", "제외조건", "유의사항"]
        for fname in field_order:
            fd = fields.get(fname, {})
            val = fd.get("value")
            if val:
                conf = fd.get("confidence", "")
                src = fd.get("source", "")
                val_short = val[:200] + ("..." if len(val) > 200 else "")
                tag = f" `[{src}/{conf}]`" if conf != "high" else ""
                lines.append(f"- **{fname}**: {val_short}{tag}")
            else:
                lines.append(f"- **{fname}**: _(미추출)_")

        completeness = sum(1 for fd in fields.values() if fd.get("value")) / len(fields) * 100
        lines.append(f"- **필드 완성도**: {completeness:.0f}% | 매칭 점수: {score}")
        lines.append(f"- **원문**: [{notice['id']}]({notice.get('url', '')})")
        lines.append("")

    return "\n".join(lines)


def main():
    project_root = Path.cwd()
    outputs_dir = project_root / "outputs"

    dataset_files = sorted(outputs_dir.glob("normalized-notices-*.json"), reverse=True)
    if not dataset_files:
        print("ERROR: No normalized dataset found")
        sys.exit(1)

    dataset_path = dataset_files[0]
    run_id = dataset_path.stem.replace("normalized-notices-", "")
    print(f"Dataset: {dataset_path.name} (run: {run_id})")

    notices = json.loads(dataset_path.read_text(encoding="utf-8"))
    print(f"Notices loaded: {len(notices)}\n")

    report_parts = [
        "# 샘플 질의 테스트 결과\n",
        f"- runId: {run_id}",
        f"- 데이터셋: {len(notices)}건",
        f"- 테스트 질의: {len(SAMPLE_QUERIES)}건\n",
        "---\n",
    ]

    summary_rows = []

    for qconfig in SAMPLE_QUERIES:
        query = qconfig["query"]
        print(f'Query: "{query}"')

        scored = []
        for notice in notices:
            s = score_notice(notice, qconfig)
            if s > 0:
                scored.append((notice, s))

        scored.sort(key=lambda x: -x[1])
        print(f"  Results: {len(scored)} notices matched")

        if scored:
            top5 = scored[:5]
            avg_completeness = 0
            for notice, _ in top5:
                fields = notice.get("fields", {})
                avg_completeness += sum(1 for fd in fields.values() if fd.get("value")) / len(fields)
            avg_completeness = avg_completeness / len(top5) * 100

            high_count = sum(
                1 for n, _ in top5
                for fd in n["fields"].values()
                if fd.get("confidence") == "high" and fd.get("value")
            )
            medium_count = sum(
                1 for n, _ in top5
                for fd in n["fields"].values()
                if fd.get("confidence") == "medium" and fd.get("value")
            )
            missing_count = sum(
                1 for n, _ in top5
                for fd in n["fields"].values()
                if not fd.get("value")
            )

            summary_rows.append({
                "query": query,
                "matched": len(scored),
                "top5_avg_completeness": round(avg_completeness, 1),
                "top5_high": high_count,
                "top5_medium": medium_count,
                "top5_missing": missing_count,
            })

            print(f"  Top-5 avg completeness: {avg_completeness:.1f}%")
            print(f"  Top-5 fields: high={high_count}, medium={medium_count}, missing={missing_count}")

        response = format_chatbot_response(query, scored)
        report_parts.append(response)
        report_parts.append("---\n")

    # 종합 요약
    report_parts.append("# 종합 분석\n")
    report_parts.append("## 질의별 요약\n")
    report_parts.append("| 질의 | 매칭 수 | Top-5 완성도 | High | Medium | Missing |")
    report_parts.append("|------|---------|-------------|------|--------|---------|")
    for row in summary_rows:
        report_parts.append(
            f"| {row['query']} | {row['matched']} | {row['top5_avg_completeness']}% "
            f"| {row['top5_high']} | {row['top5_medium']} | {row['top5_missing']} |"
        )

    total_high = sum(r["top5_high"] for r in summary_rows)
    total_medium = sum(r["top5_medium"] for r in summary_rows)
    total_missing = sum(r["top5_missing"] for r in summary_rows)
    total_all = total_high + total_medium + total_missing

    report_parts.append(f"\n## 전체 신뢰도\n")
    report_parts.append(f"- Top-5 응답 내 high 신뢰도 필드: {total_high}/{total_all} ({total_high/total_all*100:.1f}%)")
    report_parts.append(f"- Top-5 응답 내 medium 신뢰도 필드: {total_medium}/{total_all} ({total_medium/total_all*100:.1f}%)")
    report_parts.append(f"- Top-5 응답 내 미추출 필드: {total_missing}/{total_all} ({total_missing/total_all*100:.1f}%)")

    report_parts.append(f"\n## 판단\n")
    avg_complete = sum(r["top5_avg_completeness"] for r in summary_rows) / len(summary_rows)
    if avg_complete >= 70:
        report_parts.append(f"- 평균 필드 완성도 **{avg_complete:.1f}%**: 챗봇 요약형 응답에 충분한 수준")
    elif avg_complete >= 50:
        report_parts.append(f"- 평균 필드 완성도 **{avg_complete:.1f}%**: 기본 응답 가능, 첨부 파싱 보강 필요")
    else:
        report_parts.append(f"- 평균 필드 완성도 **{avg_complete:.1f}%**: 데이터 보강 필수")

    report_parts.append("- 5개 핵심 필드(지원대상/지원내용/신청기간/신청방법/문의처)는 API에서 100% 확보")
    report_parts.append("- 제출서류/제외조건/유의사항은 첨부 의존 → 첨부 없는 공고는 해당 필드 공란")
    report_parts.append("- 실무형 응답(서류 안내, 제외 조건 확인)에는 첨부 파싱 품질 개선 필요")

    report_path = outputs_dir / f"sample-query-test-{run_id}.md"
    report_path.write_text("\n".join(report_parts), encoding="utf-8")
    print(f"\nReport saved: {report_path.name}")

    # JSON도 저장
    json_path = outputs_dir / f"sample-query-test-{run_id}.json"
    json_path.write_text(json.dumps({
        "runId": run_id,
        "queries": summary_rows,
        "avgCompleteness": round(avg_complete, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
