#!/usr/bin/env python3
"""Generate Toss-style Korean purpose copy for policyfit-db records.

Usage:
  python scripts/generate-purposes-codex.py --test
  python scripts/generate-purposes-codex.py
  python scripts/generate-purposes-codex.py --force
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "policyfit-db.json"
MARKDOWN_ROOT = ROOT / "raw" / "markdown" / "20260601-224706"
MODEL = "gpt-4o-mini"
SAVE_EVERY = 100
TEST_LIMIT = 10


SYSTEM_PROMPT = """당신은 정책 지원사업을 쉬운 한국어로 바꾸는 카피라이터예요.

아래 규칙을 모두 지켜 목적 문장 하나만 작성하세요.
- 해요체로 쓰세요. 예: ~이에요, ~해요, ~드려요
- 50~100자 사이의 한 문장으로 쓰세요.
- 무엇을 지원하는지보다 왜 이 사업이 필요한지, 즉 배경과 목적에 집중하세요.
- 법령 인용(예: 「법률명」)과 딱딱한 정부 공고 표현은 빼세요.
- 지원 금액, 신청 방법, 세부 대상 같은 조건 나열은 피하세요.
- 반드시 '~사업이에요.' 또는 '~돕는 사업이에요.'로 끝내세요.
- 따옴표, 번호, 설명 없이 최종 문장만 출력하세요.

좋은 예:
경기침체로 어려운 소상공인의 운영자금 부담을 덜어주는 저금리 융자 사업이에요."""


USER_PROMPT = """다음 정책 공고의 '사업개요'를 읽고 Toss-style 한국어 목적 문장을 만들어 주세요.

제목: {title}
기관: {org}
분야: {category}

사업개요:
{overview}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate purpose fields for outputs/policyfit-db.json."
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Generate and print purposes for the first 10 records without saving.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess records even when purpose is already populated.",
    )
    return parser.parse_args()


def get_client() -> OpenAI:
    if OpenAI is None:
        print(
            "ERROR: The OpenAI Python SDK is not installed. "
            "Install it with: pip install openai>=1.0",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set. "
            "Set the environment variable and run this script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    return OpenAI(api_key=api_key)


def load_records() -> list[dict]:
    with DB_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise TypeError(f"{DB_PATH} must contain a JSON list of policy records.")

    return data


def save_records(records: list[dict]) -> None:
    tmp_path = DB_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(DB_PATH)


def detail_path(record_id: str) -> Path:
    return MARKDOWN_ROOT / record_id / "detail.md"


def extract_business_overview(markdown: str) -> str:
    heading = re.search(r"(?m)^##\s*사업개요\s*$", markdown)
    if not heading:
        return ""

    start = heading.end()
    next_heading = re.search(r"(?m)^##\s+", markdown[start:])
    end = start + next_heading.start() if next_heading else len(markdown)
    section = markdown[start:end].strip()

    section = re.sub(r"(?m)^---\s*$", " ", section)
    section = re.sub(r"\s+", " ", section)
    return section.strip()


def already_processed(record: dict) -> bool:
    purpose = str(record.get("purpose") or "").strip()
    return len(purpose) > 20


def clean_purpose(text: str) -> str:
    text = text.strip().strip("\"'“”‘’")
    text = re.sub(r"「[^」]+」", "", text)
    text = re.sub(r"\s+", " ", text)

    # Keep a single sentence if the model included explanation after the answer.
    endings = ["돕는 사업이에요.", "사업이에요."]
    for ending in endings:
        idx = text.find(ending)
        if idx != -1:
            text = text[: idx + len(ending)]
            break

    return text.strip()


def validation_issues(text: str) -> list[str]:
    issues = []
    if not (50 <= len(text) <= 100):
        issues.append(f"length is {len(text)}, expected 50-100 Korean characters")
    if "\n" in text or text.count(".") != 1:
        issues.append("must be a single sentence")
    if not (text.endswith("사업이에요.") or text.endswith("돕는 사업이에요.")):
        issues.append("must end with '~사업이에요.' or '~돕는 사업이에요.'")
    if re.search(r"「[^」]+」", text):
        issues.append("must not include legal citations")
    return issues


def call_openai(client: OpenAI, prompt: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=160,
    )
    content = response.choices[0].message.content or ""
    return clean_purpose(content)


def generate_purpose(client: OpenAI, record: dict, overview: str) -> str:
    prompt = USER_PROMPT.format(
        title=record.get("title", ""),
        org=record.get("org", ""),
        category=record.get("category", ""),
        overview=overview[:3000],
    )

    result = call_openai(client, prompt)
    issues = validation_issues(result)
    if not issues:
        return result

    retry_prompt = (
        f"{prompt}\n\n"
        f"이전 출력: {result}\n"
        f"수정해야 할 점: {', '.join(issues)}\n"
        "규칙을 모두 지켜 최종 문장 하나만 다시 작성하세요."
    )
    retry_result = call_openai(client, retry_prompt)
    retry_issues = validation_issues(retry_result)
    if retry_issues:
        print(
            f"WARNING: generated text still violates constraints for "
            f"{record.get('id')}: {', '.join(retry_issues)}",
            file=sys.stderr,
        )
    return retry_result


def process_records(records: list[dict], *, test: bool, force: bool) -> None:
    client = get_client()
    selected_records = records[:TEST_LIMIT] if test else records

    generated = 0
    skipped_existing = 0
    skipped_missing = 0
    skipped_empty_section = 0
    changed_since_save = 0

    for index, record in enumerate(selected_records, start=1):
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            print(f"WARNING: record #{index} has no id; skipping", file=sys.stderr)
            continue

        # Test mode is a dry-run preview, so it intentionally regenerates the first
        # 10 records unless --force is irrelevant. Full runs keep resume behavior.
        if not test and not force and already_processed(record):
            skipped_existing += 1
            continue

        path = detail_path(record_id)
        if not path.exists():
            print(f"WARNING: missing detail.md for {record_id}: {path}", file=sys.stderr)
            skipped_missing += 1
            continue

        markdown = path.read_text(encoding="utf-8", errors="replace")
        overview = extract_business_overview(markdown)
        if not overview:
            print(f"WARNING: no ## 사업개요 section for {record_id}", file=sys.stderr)
            skipped_empty_section += 1
            continue

        purpose = generate_purpose(client, record, overview)
        generated += 1

        if test:
            print(f"{index:02d}. {record_id} | {record.get('title', '')}")
            print(f"    {purpose}")
        else:
            record["purpose"] = purpose
            changed_since_save += 1
            print(f"[{index}/{len(records)}] {record_id}: {purpose}")

            if generated % SAVE_EVERY == 0:
                save_records(records)
                print(f"Saved intermediate results after {generated} generated records.")
                changed_since_save = 0

        time.sleep(0.2)

    if not test and changed_since_save:
        save_records(records)
        print("Saved final results.")

    print(
        "Done. "
        f"generated={generated}, "
        f"skipped_existing={skipped_existing}, "
        f"skipped_missing={skipped_missing}, "
        f"skipped_empty_section={skipped_empty_section}"
    )


def main() -> None:
    args = parse_args()
    records = load_records()
    process_records(records, test=args.test, force=args.force)


if __name__ == "__main__":
    main()
