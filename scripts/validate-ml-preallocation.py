"""Validate policy taxonomy pre-allocation outputs without rebuilding them."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-db", required=True, type=Path)
    parser.add_argument("--allocation-json", required=True, type=Path)
    parser.add_argument("--allocation-csv", required=True, type=Path)
    args = parser.parse_args()

    knowledge = json.loads(args.knowledge_db.read_text(encoding="utf-8"))
    allocation = json.loads(args.allocation_json.read_text(encoding="utf-8"))
    csv_rows = read_csv(args.allocation_csv)
    json_rows = allocation["records"]

    check(isinstance(knowledge, list), "knowledge DB must be a JSON list")
    source_ids = [row["id"] for row in knowledge]
    csv_ids = [row["record_id"] for row in csv_rows]
    json_ids = [row["record_id"] for row in json_rows]
    check(len(source_ids) == len(set(source_ids)), "knowledge DB IDs must be unique")
    check(len(csv_ids) == len(set(csv_ids)), "allocation CSV IDs must be unique")
    check(len(json_ids) == len(set(json_ids)), "allocation JSON IDs must be unique")
    check(set(source_ids) == set(csv_ids), "CSV must preserve every knowledge DB ID")
    check(set(source_ids) == set(json_ids), "JSON must preserve every knowledge DB ID")

    family_counts = Counter(row["program_family_id"] for row in json_rows)
    publication_counts = Counter(row["publication_group_id"] for row in json_rows)
    content_repeat_counts = Counter(row["content_repeat_group_id"] for row in json_rows)

    for row in json_rows:
        family_size = int(row["program_family_size"])
        publication_size = int(row["publication_group_size"])
        check(
            row["split_group_id"] == row["program_family_id"],
            f"split leakage risk for {row['record_id']}",
        )
        check(
            family_size == family_counts[row["program_family_id"]],
            f"wrong family size for {row['record_id']}",
        )
        check(
            publication_size == publication_counts[row["publication_group_id"]],
            f"wrong publication group size for {row['record_id']}",
        )
        check(
            math.isclose(float(row["family_weight"]), 1 / family_size, rel_tol=1e-7),
            f"wrong family weight for {row['record_id']}",
        )

    summary = allocation["summary"]
    representative_count = sum(bool(row["analysis_include"]) for row in json_rows)
    repeated_publication_groups = sum(size > 1 for size in publication_counts.values())
    content_repeat_candidate_groups = sum(size > 1 for size in content_repeat_counts.values())
    family_groups = sum(size > 1 for size in family_counts.values())
    records_in_families = sum(size for size in family_counts.values() if size > 1)

    expected = {
        "sourceRecords": len(source_ids),
        "analysisRepresentatives": representative_count,
        "excludedRepeatedPublications": len(source_ids) - representative_count,
        "repeatedPublicationGroups": repeated_publication_groups,
        "contentRepeatCandidateGroups": content_repeat_candidate_groups,
        "programFamilyGroups": family_groups,
        "recordsInProgramFamilies": records_in_families,
        "fuzzyReviewCandidates": len(allocation["fuzzyReviewCandidates"]),
    }
    check(summary == expected, f"summary mismatch: expected={expected}, actual={summary}")

    result = {
        "status": "PASS",
        "summary": summary,
        "sha256": {
            "knowledgeDb": sha256(args.knowledge_db),
            "allocationJson": sha256(args.allocation_json),
            "allocationCsv": sha256(args.allocation_csv),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
