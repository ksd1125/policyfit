"""Build conservative pre-allocation data for policy taxonomy experiments.

The source knowledge DB is never modified. The generated allocation keeps every
notice while identifying representative records, repeated publication groups,
program families, and fuzzy review candidates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
from pathlib import Path


GENERIC_TITLE_PHRASES = (
    "지원 계획 공고",
    "지원계획 공고",
    "사업 시행 공고",
    "사업시행 공고",
    "사업 공고",
    "사업공고",
    "모집 공고",
    "모집공고",
    "참여기업 모집",
    "기업 모집",
    "대상자 모집",
    "지원사업",
    "재공고",
    "추가모집",
    "연장공고",
    "변경공고",
    "공고",
)


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a

    def groups(self) -> list[list[int]]:
        result: dict[int, list[int]] = defaultdict(list)
        for item in range(len(self.parent)):
            result[self.find(item)].append(item)
        return list(result.values())


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: object) -> str:
    return "".join(ch for ch in normalize_text(value) if ch.isalnum())


def family_title(value: object) -> str:
    text = normalize_text(value)
    if text.startswith("[") and "]" in text:
        text = text.split("]", 1)[1]
    text = re.sub(r"20\d{2}\s*년", " ", text)
    text = re.sub(r"\d+\s*차", " ", text)
    text = text.replace("상반기", " ").replace("하반기", " ")
    for phrase in GENERIC_TITLE_PHRASES:
        text = text.replace(phrase, " ")
    return "".join(ch for ch in text if ch.isalnum())


def normalized_structure(value: object) -> object:
    if isinstance(value, dict):
        return {key: normalized_structure(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted(normalized_structure(item) for item in value)
    return normalize_text(value)


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def substantive_signature(record: dict) -> str:
    application = {
        key: value
        for key, value in record.get("application", {}).items()
        if key not in {"period", "periodType"}
    }
    value = {
        "support": record.get("support", {}),
        "eligibility": record.get("eligibility", {}),
        "application": application,
        "institution": record.get("institution"),
        "executor": record.get("executor"),
    }
    return digest(normalized_structure(value))


def quality_score(record: dict) -> tuple[int, int, int, str]:
    quality = record.get("quality", {})
    grade = {"detailed": 3, "moderate": 2, "vague": 1}.get(quality.get("grade"), 0)
    return (
        grade,
        len(quality.get("sources", [])),
        int(quality.get("contentLength") or 0),
        str(record.get("registeredAt") or ""),
    )


def add_same_key_groups(groups: dict[object, list[int]], uf: UnionFind) -> None:
    for members in groups.values():
        if len(members) < 2:
            continue
        first = members[0]
        for item in members[1:]:
            uf.union(first, item)


def group_ids(prefix: str, groups: list[list[int]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for number, members in enumerate(
        sorted(groups, key=lambda items: (min(items), len(items))), start=1
    ):
        group_id = f"{prefix}-{number:04d}"
        for item in members:
            result[item] = group_id
    return result


def make_group_rows(
    records: list[dict],
    groups: list[list[int]],
    id_map: dict[int, str],
    representatives: dict[int, int] | None = None,
) -> list[dict]:
    rows = []
    for members in sorted(groups, key=lambda items: (-len(items), min(items))):
        if len(members) < 2:
            continue
        root = members[0]
        rep = representatives[root] if representatives else max(members, key=lambda i: quality_score(records[i]))
        rows.append(
            {
                "groupId": id_map[root],
                "size": len(members),
                "representativeId": records[rep]["id"],
                "memberIds": [records[item]["id"] for item in members],
                "titles": sorted({records[item]["title"] for item in members}),
            }
        )
    return rows


@dataclass
class AllocationResult:
    payload: dict
    mapping_rows: list[dict]


def build_allocation(records: list[dict]) -> AllocationResult:
    count = len(records)
    publication_uf = UnionFind(count)
    content_repeat_uf = UnionFind(count)

    strict_title: dict[tuple, list[int]] = defaultdict(list)
    exact_substance: dict[str, list[int]] = defaultdict(list)
    regional_summary: dict[tuple, list[int]] = defaultdict(list)
    for idx, record in enumerate(records):
        strict_title[
            (
                compact_text(record.get("title")),
                record.get("region"),
                record.get("institution"),
                record.get("executor"),
                compact_text(record.get("support", {}).get("summary")),
                normalize_text(record.get("application", {}).get("period")),
            )
        ].append(idx)
        exact_substance[substantive_signature(record)].append(idx)
        summary = compact_text(record.get("support", {}).get("summary"))
        if len(summary) >= 40:
            regional_summary[
                (
                    summary,
                    record.get("region"),
                    record.get("institution"),
                    record.get("executor"),
                    record.get("category"),
                    record.get("subcategory"),
                )
            ].append(idx)

    add_same_key_groups(strict_title, publication_uf)
    add_same_key_groups(exact_substance, content_repeat_uf)
    add_same_key_groups(regional_summary, content_repeat_uf)
    publication_groups = publication_uf.groups()
    content_repeat_groups = content_repeat_uf.groups()

    publication_representative: dict[int, int] = {}
    representative_for_item: dict[int, int] = {}
    for members in publication_groups:
        representative = max(members, key=lambda i: quality_score(records[i]))
        for item in members:
            publication_representative[item] = representative
            representative_for_item[item] = representative

    family_uf = UnionFind(count)
    family_keys: dict[str, list[int]] = defaultdict(list)
    summary_keys: dict[str, list[int]] = defaultdict(list)
    for idx, record in enumerate(records):
        key = family_title(record.get("title"))
        if len(key) >= 8:
            family_keys[key].append(idx)
        summary = compact_text(record.get("support", {}).get("summary"))
        if len(summary) >= 80:
            summary_keys[summary].append(idx)
    add_same_key_groups(family_keys, family_uf)
    add_same_key_groups(summary_keys, family_uf)
    for members in publication_groups:
        for item in members[1:]:
            family_uf.union(members[0], item)
    for members in content_repeat_groups:
        for item in members[1:]:
            family_uf.union(members[0], item)
    family_groups = family_uf.groups()

    publication_id = group_ids("PUB", publication_groups)
    content_repeat_id = group_ids("CNT", content_repeat_groups)
    family_id = group_ids("FAM", family_groups)
    publication_size = {}
    family_size = {}
    for members in publication_groups:
        for item in members:
            publication_size[item] = len(members)
    for members in family_groups:
        for item in members:
            family_size[item] = len(members)

    representatives = [
        idx for idx in range(count) if representative_for_item[idx] == idx
    ]
    review_candidates = []
    for pos, left in enumerate(representatives):
        left_record = records[left]
        left_key = family_title(left_record.get("title"))
        if len(left_key) < 8:
            continue
        for right in representatives[pos + 1 :]:
            if family_id[left] == family_id[right]:
                continue
            right_record = records[right]
            if left_record.get("category") != right_record.get("category"):
                continue
            right_key = family_title(right_record.get("title"))
            if len(right_key) < 8:
                continue
            similarity = SequenceMatcher(None, left_key, right_key).ratio()
            if similarity >= 0.86:
                review_candidates.append(
                    {
                        "leftId": left_record["id"],
                        "rightId": right_record["id"],
                        "similarity": round(similarity, 4),
                        "leftTitle": left_record["title"],
                        "rightTitle": right_record["title"],
                    }
                )
    review_candidates = sorted(
        review_candidates, key=lambda item: (-item["similarity"], item["leftId"], item["rightId"])
    )[:200]

    mapping_rows = []
    for idx, record in enumerate(records):
        rep_idx = representative_for_item[idx]
        mapping_rows.append(
            {
                "record_id": record["id"],
                "title": record["title"],
                "region": record.get("region") or "",
                "category": record.get("category") or "",
                "subcategory": record.get("subcategory") or "",
                "publication_group_id": publication_id[idx],
                "publication_group_size": publication_size[idx],
                "representative_id": records[rep_idx]["id"],
                "analysis_include": idx == rep_idx,
                "content_repeat_group_id": content_repeat_id[idx],
                "program_family_id": family_id[idx],
                "program_family_size": family_size[idx],
                "family_weight": round(1 / family_size[idx], 8),
                "split_group_id": family_id[idx],
            }
        )

    repeated_publication_groups = [g for g in publication_groups if len(g) > 1]
    repeated_content_groups = [g for g in content_repeat_groups if len(g) > 1]
    repeated_family_groups = [g for g in family_groups if len(g) > 1]
    payload = {
        "schemaVersion": "1.0",
        "purpose": "Conservative pre-allocation for policy taxonomy ML experiments",
        "principles": [
            "Never delete source notices.",
            "Use one representative per repeated publication group for ML input.",
            "Keep regional and periodic variants in a program family.",
            "Keep every program family in one split to prevent train-test leakage.",
            "Use inverse family size as a sensitivity-analysis weight.",
            "Review fuzzy candidates manually before automatic merging.",
        ],
        "summary": {
            "sourceRecords": count,
            "analysisRepresentatives": len(representatives),
            "excludedRepeatedPublications": count - len(representatives),
            "repeatedPublicationGroups": len(repeated_publication_groups),
            "contentRepeatCandidateGroups": len(repeated_content_groups),
            "programFamilyGroups": len(repeated_family_groups),
            "recordsInProgramFamilies": sum(len(g) for g in repeated_family_groups),
            "fuzzyReviewCandidates": len(review_candidates),
        },
        "publicationGroups": make_group_rows(
            records, repeated_publication_groups, publication_id, representative_for_item
        ),
        "contentRepeatCandidates": make_group_rows(
            records, repeated_content_groups, content_repeat_id
        ),
        "programFamilies": make_group_rows(records, repeated_family_groups, family_id),
        "fuzzyReviewCandidates": review_candidates,
        "records": mapping_rows,
    }
    return AllocationResult(payload=payload, mapping_rows=mapping_rows)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render_html(result: AllocationResult) -> str:
    summary = result.payload["summary"]
    families = result.payload["programFamilies"][:15]
    candidates = result.payload["fuzzyReviewCandidates"][:20]

    def family_rows() -> str:
        return "".join(
            "<tr>"
            f"<td>{escape(item['groupId'])}</td>"
            f"<td>{item['size']}</td>"
            f"<td>{escape(item['titles'][0])}</td>"
            f"<td>{len(item['titles'])}</td>"
            "</tr>"
            for item in families
        )

    def candidate_rows() -> str:
        return "".join(
            "<tr>"
            f"<td>{item['similarity']:.3f}</td>"
            f"<td>{escape(item['leftTitle'])}</td>"
            f"<td>{escape(item['rightTitle'])}</td>"
            "</tr>"
            for item in candidates
        )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>정책상품 ML 분류 실험 및 중복 사전 배치 계획</title>
<style>
body{{font-family:Arial,"Malgun Gothic",sans-serif;line-height:1.65;color:#24332f;background:#f5f1e8;margin:0}}
main{{max-width:1080px;margin:auto;padding:36px 22px 70px}}
h1{{font-size:30px;line-height:1.25}}h2{{margin-top:34px;border-left:5px solid #2e806d;padding-left:12px}}
.hero,.box{{background:#fffdfa;border-radius:12px;padding:18px 20px;margin:14px 0;box-shadow:0 2px 10px #0000000d}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}
.metric{{background:#e8f3ed;border-radius:10px;padding:12px}}.metric b{{display:block;font-size:24px;color:#276b5d}}
table{{border-collapse:collapse;width:100%;background:#fffdfa;font-size:14px}}th,td{{border:1px solid #ddd4c5;padding:8px;vertical-align:top}}th{{background:#e8f3ed}}
code{{background:#e9ece8;padding:2px 5px;border-radius:4px}}li{{margin:5px 0}}
</style></head><body><main>
<h1>정책상품 ML 분류 실험 및 중복 사전 배치 계획</h1>
<p>원본 공고를 보존하면서 동일 내용 반복, 지역별 변형, 반복사업을 ML 분석 전에 분리한다.</p>
<section class="hero"><b>핵심 원칙</b><p>중복을 삭제하지 않는다. ML 구조 발견에는 대표 공고만 사용하고, 반복사업은 <code>program_family_id</code>로 묶는다. 학습·검증 분할은 개별 공고가 아니라 사업군 단위로 수행한다.</p></section>
<h2>1. 현재 사전 배치 결과</h2>
<div class="grid">
<div class="metric"><b>{summary['sourceRecords']}</b>원본 공고</div>
<div class="metric"><b>{summary['analysisRepresentatives']}</b>ML 입력 대표 공고</div>
<div class="metric"><b>{summary['excludedRepeatedPublications']}</b>대표 공고로 통합한 반복 공고</div>
<div class="metric"><b>{summary['contentRepeatCandidateGroups']}</b>내용 반복 검토 그룹</div>
<div class="metric"><b>{summary['programFamilyGroups']}</b>복수 공고 사업군</div>
<div class="metric"><b>{summary['recordsInProgramFamilies']}</b>사업군 포함 공고</div>
<div class="metric"><b>{summary['fuzzyReviewCandidates']}</b>추가 검토 후보</div>
</div>
<h2>2. 세 단계 구분</h2>
<table><tr><th>단계</th><th>목적</th><th>처리</th></tr>
<tr><td>반복 공고 통합</td><td>동일 내용이 ML 빈도를 왜곡하지 않도록 방지</td><td><code>publication_group_id</code>별 대표 공고 하나만 입력</td></tr>
<tr><td>내용 반복 후보</td><td>추출 필드가 같아도 의미 차이가 있을 수 있음</td><td><code>content_repeat_group_id</code>를 부여하되 자동 삭제하지 않음</td></tr>
<tr><td>사업군 배치</td><td>지역별·회차별 변형의 관계 보존</td><td><code>program_family_id</code>를 부여하고 같은 split에 배치</td></tr>
<tr><td>민감도 분석</td><td>반복사업의 과대대표 여부 점검</td><td>원자료 결과와 <code>family_weight=1/n</code> 결과 비교</td></tr>
</table>
<h2>3. 분류 방법론 비교</h2>
<table><tr><th>후보 방법</th><th>입력</th><th>역할</th></tr>
<tr><td>LCA</td><td>범주형 정책 속성</td><td>잠재 정책유형 발견, BIC·entropy·BLRT 비교</td></tr>
<tr><td>Gower distance + PAM</td><td>범주형·수치형 혼합 속성</td><td>대표 정책 중심 군집, Silhouette·안정성 평가</td></tr>
<tr><td>Gower distance + 계층형 군집화</td><td>혼합 속성</td><td>상위·하위 taxonomy 후보 확인</td></tr>
<tr><td>문장 임베딩 + 군집화</td><td>공고 요약 텍스트</td><td>구조화 속성에서 놓친 의미를 보완하는 민감도 분석</td></tr>
</table>
<h2>4. 공통 평가 기준</h2>
<table><tr><th>평가 축</th><th>지표</th><th>판정 방식</th></tr>
<tr><td>응집도·분리도</td><td>Silhouette, Davies-Bouldin, Calinski-Harabasz</td><td>동일 데이터에서 후보 모형 상대 비교</td></tr>
<tr><td>재표집 안정성</td><td>Bootstrap Jaccard</td><td>500~1,000회 재표집. 0.75 이상 권장, 0.85 이상이면 안정적</td></tr>
<tr><td>기관·연도 재현성</td><td>ARI, NMI</td><td>하위 표본에서도 구조가 유지되는지 확인</td></tr>
<tr><td>LCA 모형 선택</td><td>BIC, entropy, BLRT</td><td>군집 수 <code>k</code>별 상대 비교</td></tr>
<tr><td>반복사업 영향</td><td>가중·비가중 결과 비교</td><td>사업군 가중치 적용 전후 결론 변화 보고</td></tr>
</table>
<h2>5. 주요 사업군 예시</h2>
<table><tr><th>사업군</th><th>공고 수</th><th>대표 제목</th><th>제목 변형 수</th></tr>{family_rows()}</table>
<h2>6. 자동 병합하지 않은 유사 후보</h2>
<p>아래 후보는 제목 유사도가 높지만 의미가 같다고 단정하지 않는다. 후속 규칙 정교화용 검토 목록이다.</p>
<table><tr><th>유사도</th><th>공고 A</th><th>공고 B</th></tr>{candidate_rows()}</table>
<h2>7. 실행 순서</h2>
<ol>
<li>대표 공고만 사용한 분석표와 전체 공고 분석표를 함께 만든다.</li>
<li><code>k=4~20</code>에서 LCA, PAM, 계층형 군집화를 실행한다.</li>
<li>각 방법에 동일한 통계 지표와 bootstrap 안정성 검사를 적용한다.</li>
<li>사업군 가중치 적용 전후 결과를 비교한다.</li>
<li>단일 계층 taxonomy가 불안정하면 다축 태그 구조를 채택한다.</li>
</ol>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("Expected a non-empty JSON list")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = build_allocation(records)
    (args.output_dir / "ml-preallocation.json").write_text(
        json.dumps(result.payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(args.output_dir / "ml-preallocation.csv", result.mapping_rows)
    (args.output_dir / "ml-taxonomy-experiment-plan-20260602.html").write_text(
        render_html(result), encoding="utf-8"
    )
    print(json.dumps(result.payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
