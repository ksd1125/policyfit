#!/usr/bin/env python3
"""Codex CLI를 통해 목적문을 배치 생성.

Codex CLI가 자체 인증(OAuth)을 가지므로 별도 API 키 불필요.
subprocess로 codex 호출 → 결과를 policyfit-db.json에 반영.

사용법:
  python scripts/generate-via-codex-cli.py          # 개선 필요한 건만
  python scripts/generate-via-codex-cli.py --test    # 5건 테스트
  python scripts/generate-via-codex-cli.py --force   # 전수 재생성
"""

import json, sys, os, re, subprocess, time, argparse
from pathlib import Path

# Windows cp949 콘솔에서 한글/이모지 출력 시 인코딩 에러 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "policyfit-db.json"
MD_BASE = ROOT / "raw" / "markdown" / "20260601-224706"
CACHE_PATH = ROOT / "outputs" / "_purpose_cache_codex.json"

PROMPT_TEMPLATE = """아래 정책 공고의 사업개요를 읽고, 토스(Toss) 앱 스타일의 한 줄 목적 문장을 만들어주세요.

규칙:
- 해요체 (예: ~이에요, ~해요)
- 50~100자, 한 문장
- "왜 이 사업이 필요한지" 배경과 목적에 집중
- 법령, 금액, 대상 조건은 제외
- "~사업이에요." 로 끝내기
- 따옴표 없이 문장만 출력

제목: {title}
기관: {org}
분야: {category}

사업개요:
{overview}

목적 한 줄:"""


# 재시도용 강화 프롬프트 — 이전 결과의 약점을 명시
RETRY_PROMPT_TEMPLATE = """이전에 만든 목적 문장이 부족했어요. 다시 만들어주세요.

이전 시도: {previous}
약점: {weakness}

규칙(반드시 모두 충족):
- 해요체로 끝 ("~사업이에요.")
- 50~100자 한 문장
- 누가 어려움을 겪고 있어서(공감) 이 사업이 무엇으로 그들을 돕는지(수단)를 모두 담아주세요
- 대상자를 구체적 명사로 명시 (소상공인/중소기업/창업자/기업/농가/예술인 등)
- 법령/금액/대상 조건/기관명은 제외
- 따옴표 없이 문장만 출력

좋은 예시:
"막막한 창업 길에서 자금난을 겪는 소상공인이 안정적으로 가게를 운영하도록 돕는 사업이에요."
"디지털 전환이 어려운 중소 제조기업이 스마트공장 기술을 도입하도록 돕는 사업이에요."

제목: {title}
사업개요:
{overview}

다시 만든 목적 한 줄:"""


def get_overview(pid):
    detail = MD_BASE / pid / "detail.md"
    if not detail.exists():
        return ""
    text = detail.read_text(encoding="utf-8")
    idx = text.find("## 사업개요")
    if idx < 0:
        return text[:800]
    start = idx + len("## 사업개요")
    end = text.find("##", start)
    if end < 0:
        end = len(text)
    section = text[start:end].strip()
    return re.sub(r"\s+", " ", section)[:800]


def call_codex(prompt):
    """codex CLI를 quiet 모드로 호출하여 결과 텍스트 반환"""
    try:
        out_file = str(ROOT / "outputs" / "_codex_out.txt")
        codex_path = os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")
        if os.path.exists(out_file):
            os.remove(out_file)
        # 프롬프트는 stdin으로 전달 (긴 한글 인자 깨짐 방지)
        # 결과는 -o 파일로만 수신 (stdout cp949 디코딩 에러 방지)
        subprocess.run(
            [codex_path, "exec", "--skip-git-repo-check",
             "-c", "model_reasoning_effort=low",
             "-o", out_file, "-"],
            input=prompt.encode("utf-8"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180, shell=True,
        )
        # -o 파일에서 결과 읽기
        if not os.path.exists(out_file):
            return None
        with open(out_file, encoding="utf-8") as f:
            result_text = f.read().strip()
        os.remove(out_file)
        result = type('R', (), {'stdout': result_text})()
        output = result.stdout.strip()
        # 따옴표/번호/마크다운 제거
        output = output.strip('"\'""''')
        output = re.sub(r"^\d+[.)]\s*", "", output)
        # 여러 줄이면 마지막 줄 (codex가 설명을 덧붙일 수 있음)
        lines = [l.strip() for l in output.split("\n") if l.strip() and "사업이에요" in l]
        if lines:
            output = lines[-1]
        return output if len(output) > 15 else None
    except Exception as e:
        print(f"  [warn] codex error: {e}", file=sys.stderr)
        return None


def needs_improvement(purpose):
    if len(purpose) < 40:
        return True
    if not purpose.endswith(("이에요.", "해요.", "드려요.")):
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="5건만 테스트")
    parser.add_argument("--force", action="store_true", help="전수 재생성")
    args = parser.parse_args()

    with open(DB_PATH, encoding="utf-8") as f:
        policies = json.load(f)

    # 캐시 로드
    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)

    # 대상 선별
    targets = []
    for i, p in enumerate(policies):
        pid = p["id"]
        if pid in cache and not args.force:
            p["purpose"] = cache[pid]
            continue
        if args.force or needs_improvement(p["purpose"]):
            targets.append(i)

    if args.test:
        targets = targets[:5]

    total = len(targets)
    print(f"처리 대상: {total}건 (전체 {len(policies)}건, 캐시 {len(cache)}건)")

    generated = 0
    failed = 0

    for n, idx in enumerate(targets):
        p = policies[idx]
        overview = get_overview(p["id"])
        if not overview:
            failed += 1
            continue

        prompt = PROMPT_TEMPLATE.format(
            title=p["title"],
            org=p["org"],
            category=p["category"],
            overview=overview[:600],
        )

        result = call_codex(prompt)

        if result:
            policies[idx]["purpose"] = result
            cache[p["id"]] = result
            generated += 1
            print(f"  [{n+1}/{total}] {p['title'][:30]} → {result[:60]}")
        else:
            failed += 1
            print(f"  [{n+1}/{total}] {p['title'][:30]} → FAILED")

        # 10건마다 저장
        if generated > 0 and generated % 10 == 0:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(policies, f, ensure_ascii=False, indent=2)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"  [saved] 중간 저장 ({generated}건)")

        time.sleep(1)  # rate limiting

    # 최종 저장
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n완료: 생성 {generated}건, 실패 {failed}건")
    print(f"→ {DB_PATH}")


if __name__ == "__main__":
    main()
