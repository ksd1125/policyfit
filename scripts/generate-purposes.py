#!/usr/bin/env python3
"""Gemini API로 원본 공고문을 읽고 토스 스타일 목적문을 자동 생성.

사용법:
  1) .env.local에 GEMINI_API_KEY=... 추가
  2) python scripts/generate-purposes.py
  3) 결과: outputs/policyfit-db.json 의 purpose 필드가 갱신됨

진행률 표시, 실패 시 기존 목적 유지, 증분 실행 가능.
"""

import json, os, sys, re, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
POLICYFIT_DB = ROOT / "outputs" / "policyfit-db.json"
MD_BASE = ROOT / "raw" / "markdown" / "20260601-224706"
CACHE_FILE = ROOT / "outputs" / "_purpose_cache.json"
ENV_FILE = ROOT / ".env.local"

# ── API 키 로드 ──
def load_api_key():
    # 1) 환경변수
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    # 2) .env.local
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


# ── 공고문 텍스트 추출 ──
def get_announcement_text(pblancId):
    """원본 공고문에서 핵심 텍스트를 추출 (최대 1500자)"""
    pdir = MD_BASE / pblancId

    # 1) detail.md (사업개요)
    detail = pdir / "detail.md"
    detail_text = ""
    if detail.exists():
        detail_text = detail.read_text(encoding="utf-8")

    # 2) print_*.md (상세 공고문) — 있으면 더 풍부
    print_text = ""
    if pdir.exists():
        for f in pdir.iterdir():
            if f.name.startswith("print_") and f.name.endswith(".md"):
                print_text = f.read_text(encoding="utf-8")[:2000]
                break

    # 조합: print > detail (더 상세)
    text = print_text if len(print_text) > 200 else detail_text
    # 1500자로 제한 (토큰 절약)
    return text[:1500]


# ── Gemini 프롬프트 ──
SYSTEM_PROMPT = """당신은 정책 소개 카피라이터입니다. 토스(Toss) 앱처럼 친숙하고 따뜻한 해요체로 정책 사업의 목적을 한 줄로 작성합니다.

규칙:
1. "이 사업이 왜 존재하는지" — 배경과 목적을 담아주세요
2. 해요체 사용 (~이에요, ~해요, ~드려요)
3. 법령명(「...」), 조항(제N조), "다음과 같이 공고합니다" 같은 관공서 문구는 제거
4. 전문 용어를 쉽게 풀어주세요 (경영애로 → 경영 어려움, 담보력 → 담보)
5. 50~100자 사이, 한 문장으로
6. 지원 금액이나 대상은 넣지 마세요 — 별도 필드에 있으니까요
7. "~을/를 지원하는 사업이에요" 또는 "~을/를 돕는 사업이에요"로 끝내주세요

좋은 예시:
- "경기침체로 어려운 소상공인의 운영자금 부담을 덜어주는 저금리 융자 사업이에요."
- "온라인 판로가 필요한 소상공인의 스마트스토어 입점과 콘텐츠 제작을 돕는 사업이에요."
- "예비창업자의 아이디어를 사업으로 키울 수 있도록 자금과 멘토링을 지원하는 사업이에요."
- "수출을 처음 시도하는 중소기업의 해외 마케팅과 통관 비용을 지원하는 사업이에요."

나쁜 예시 (하지 마세요):
- "중소기업기본법 제2조에 따라..." (법령 제거)
- "최대 3천만원 지원" (금액은 넣지 마세요)
- "소상공인 대상" (대상은 넣지 마세요)
- "다음과 같이 공고합니다" (관공서 문구 제거)"""

USER_TEMPLATE = """아래 공고문을 읽고, 이 사업의 목적을 토스 스타일 한 줄(50~100자)로 작성해주세요.

제목: {title}
카테고리: {category}

공고문:
{text}

목적 한 줄:"""


def generate_purpose_gemini(model, title, category, text):
    """Gemini API로 목적문 생성"""
    prompt = USER_TEMPLATE.format(title=title, category=category, text=text)
    try:
        response = model.generate_content(
            [{"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}],
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 200,
            },
        )
        result = response.text.strip()
        # 앞뒤 따옴표 제거
        result = result.strip('"\'""''')
        # 너무 길면 자르기
        if len(result) > 120:
            cut = result[:120].rfind(".")
            if cut > 40:
                result = result[:cut + 1]
        return result
    except Exception as e:
        print(f"  ⚠ API error: {e}")
        return None


def main():
    api_key = load_api_key()
    if not api_key:
        print("❌ GEMINI_API_KEY가 없습니다.")
        print("   .env.local에 GEMINI_API_KEY=... 를 추가하거나")
        print("   환경변수로 설정해주세요.")
        print("   발급: https://aistudio.google.com → Get API Key")
        sys.exit(1)

    # Gemini 초기화
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # policyfit-db.json 로드
    with open(POLICYFIT_DB, encoding="utf-8") as f:
        policies = json.load(f)

    # 캐시 로드 (증분 실행용)
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)

    total = len(policies)
    cached_count = 0
    generated_count = 0
    failed_count = 0

    print(f"정책핏 목적문 자동 생성 (Gemini)")
    print(f"전체: {total}건, 캐시: {len(cache)}건")
    print(f"{'='*50}")

    for i, policy in enumerate(policies):
        pid = policy["id"]

        # 캐시 히트 — 이미 생성된 건 건너뛰기
        if pid in cache:
            policy["purpose"] = cache[pid]
            cached_count += 1
            continue

        # 원본 공고문 텍스트 추출
        text = get_announcement_text(pid)
        if not text or len(text) < 50:
            failed_count += 1
            continue

        # Gemini 호출
        result = generate_purpose_gemini(
            model, policy["title"], policy["category"], text
        )

        if result and len(result) > 15:
            policy["purpose"] = result
            cache[pid] = result
            generated_count += 1
        else:
            failed_count += 1

        # 진행률 표시
        done = cached_count + generated_count + failed_count
        if done % 10 == 0 or done == total:
            pct = done * 100 // total
            print(f"  [{pct:3d}%] {done}/{total} — 생성: {generated_count}, 실패: {failed_count}")

        # Rate limiting (Gemini 무료: 15 RPM)
        if generated_count % 14 == 0 and generated_count > 0:
            print(f"  ⏳ Rate limit 대기 (60초)...")
            time.sleep(62)

        # 50건마다 중간 저장
        if generated_count % 50 == 0 and generated_count > 0:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"  💾 캐시 중간 저장 ({len(cache)}건)")

    # 최종 저장
    with open(POLICYFIT_DB, "w", encoding="utf-8") as f:
        json.dump(policies, f, ensure_ascii=False, indent=2)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"완료!")
    print(f"  생성: {generated_count}건")
    print(f"  캐시: {cached_count}건")
    print(f"  실패: {failed_count}건 (기존 목적 유지)")
    print(f"  → {POLICYFIT_DB}")
    print(f"  → 캐시: {CACHE_FILE}")

    # 샘플 출력
    print(f"\n=== 샘플 ===")
    import random
    random.seed(42)
    for i in random.sample(range(len(policies)), min(5, len(policies))):
        p = policies[i]
        print(f"[{i}] {p['title'][:40]}")
        print(f"     {p['purpose']}")
        print()


if __name__ == "__main__":
    main()
