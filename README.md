# 메일용 경량 handoff 안내

이 묶음은 메일 전달용 경량 패키지입니다.

## 포함한 것

- 진행 결과 및 향후 계획 요약
- 수집 요약
- 유형화 검토 결과
- API 수집 스크립트
- 유형화 분석 스크립트
- 테스트 코드
- 설계/작업 메모

## 제외한 것

- `raw\api` 원본 수집 데이터
- `raw\html` 상세 HTML 원본
- `raw\files` 첨부/출력파일 원본
- 대용량 ZIP

## 다음 작업 시작점

1. `20260601-progress-and-plan-summary.html` 확인
2. `notice-type-analysis-20260601-131729.html` 확인
3. `scripts\collect-bizinfo.mjs`로 수집 구조 확인
4. `scripts\analyze-notice-types.mjs`로 유형화 구조 확인
5. 이후 원본 데이터는 별도 환경에서 다시 수집 또는 별도 전달본 사용
