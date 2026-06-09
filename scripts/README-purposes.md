# 정책핏 목적문 파이프라인

새 공고가 들어왔을 때 "이 사업이 왜 필요한지"를 토스 스타일 해요체 한 줄로
자동 생성·검증·반영하는 파이프라인. 현재 795건 평균 **90.7점 (A+B 100%)**.

## TL;DR — 새 공고 처리

```bash
# 1) 데이터 수집·정제 (선행, 기존 체인)
node scripts/collect-bizinfo.mjs          # 기업마당 API 수집
python scripts/normalize-notices.py       # 8필드 정규화
python scripts/build-knowledge-db.py      # 분류 + knowledge-db.json

# 2) 목적문 파이프라인 (한 방)
python scripts/refresh-purposes.py --engine codex
#   build(룰) → 미달분 식별 → Codex 생성 → 검증 → 머지 → 리포트
```

LLM 없이 룰 베이스 + 기존 캐시만:
```bash
python scripts/refresh-purposes.py --build-only
```

## 구성 (목적문 관련 스크립트)

| 스크립트 | 역할 | 입력 → 출력 |
|----------|------|-------------|
| `build-policyfit-db.py` | **룰 베이스 생성기**. 원본 공고문 `detail.md`/`print_*.md`에서 사업목적 직접 추출 + `tossify()` 토스 변환. 실패 시 v2 키워드 폴백 | `knowledge-db.json` → `policyfit-db.json` |
| `score-purposes.py` | **품질 채점기**. 형식/내용/톤앤매너 + 가독성·논리성·중언부언·비문 (0~100점) | purpose → 점수+이슈 |
| `generate-via-codex-cli.py` | **Codex CLI 생성기**. 미달 건만 LLM 생성, 캐시 증분 | detail.md → `_purpose_cache_codex.json` |
| `generate-purposes.py` | **Gemini API 생성기** (대안) | detail.md → `_purpose_cache.json` |
| `merge-purposes.py` | **머지**. 캐시 + 룰 베이스 중 점수 높은 쪽 채택 | 캐시 → `policyfit-db.json` |
| `refresh-purposes.py` | **오케스트레이터**. 위 단계를 묶어 자동 QA 루프 실행 | — |

## 데이터 vs 로직 (중요)

- **로직** (재실행 가능): 위 `.py` 스크립트들
- **캐시** (결과물, 재생성 불가): LLM/수작업 생성분
  - `outputs/_claude_batch.json` — 수작업·Claude 작성분 (507건)
  - `outputs/_purpose_cache_codex.json` — Codex 생성분 (375건)

> ⚠️ **목적문을 직접 고칠 땐 반드시 캐시(`_claude_batch.json`)에 반영**할 것.
> `policyfit-db.json`만 수정하면 `build` 재실행 시 날아간다.
> `merge-purposes.py`가 캐시를 기준으로 DB를 덮어쓰기 때문.

## 파이프라인 흐름 (refresh-purposes.py)

```
1. build      build-policyfit-db.py
              → 원문에서 목적 추출 + tossify (룰, ~52점 베이스)
2. score      score_purpose() 로 threshold(기본 70) 미만 식별
3. generate   미달분만 LLM 생성 (codex/gemini), 캐시 증분
4. verify     재채점 → 여전히 미달이면 max-retries 까지 재시도
5. merge      캐시 + 룰 중 고득점 채택 → policyfit-db.json
6. report     최종 등급 분포 출력
```

옵션:
- `--engine codex|gemini|none` (기본 none = 룰+기존 캐시만)
- `--threshold 70` (합격선, B등급)
- `--max-retries 2` (재생성 횟수)
- `--build-only` (1단계만)

## 품질 기준 (score-purposes.py)

100점 = 형식 40 + 내용 40 + 톤앤매너 20, 문장품질 감점.

- **형식**: 해요체 종결(`~사업이에요`), 길이 45~100자, 한 문장, 관공서 문체 없음
- **내용**: 동기(문제해결형 "어려운"/기회확대형 "경쟁력"), 도움 표현, 대상자 명시
- **톤**: 동기+도움 결합, 금액·법령 미포함
- **감점**: 중언부언(-8), 비문(-10), 가독성(-5), 논리성(-10)

수동 보정 도구: `outputs/policyfit/editor.html` (브라우저에서 필터·편집·JSON 다운로드)

## 산출 스키마 (policyfit-db.json)

```jsonc
{
  "purpose": "담보가 부족한 경북 소상공인이 보증과 이자 지원으로 자금난을 덜도록 돕는 사업이에요.",  // 목적 (토스 스타일)
  "targetShort": "소상공인",        // 대상 축약 (카드용)
  "targetDetail": "...",            // 대상 상세 (시트용)
  "benefits": "...",                // 지원내용 (시트용)
  "legalBasis": ["소상공인기본법"],  // 근거 법령 (정책입안자 필터용)
  // ... 그 외 기존 필드
}
```
