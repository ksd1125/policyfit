# 기업마당 공고 유형화 검토

- 분석 대상 runId: 20260601-131729
- 분석 공고 수: 778건

## 1. 문서유형
- hwp_core: 403건
- html_plus_print: 274건
- bundle_package: 53건
- pdf_core: 30건
- mixed_attachment: 18건

## 2. 지원유형
- funding: 268건
- consulting: 224건
- commercialization: 210건
- facility: 48건
- education_event: 25건
- startup: 3건

## 3. 대상유형
- sme: 455건
- small_business: 180건
- startup_venture: 106건
- social_enterprise: 22건
- other: 15건

## 4. 접수유형
- website: 308건
- mixed: 187건
- email: 150건
- visit: 108건
- other: 24건
- post: 1건

## 5. 신청기간 유형
- budget_exhausted: 343건
- date_range: 324건
- other: 47건
- always_open: 45건
- varies_by_program: 14건
- announced_later: 5건

## 6. 권장 파싱 순서
1. 메타데이터 파싱: 공고명, 기관, 대상, 신청기간, 대분류/세부분류 확보
2. 상세 HTML 파싱: 사업개요, 신청방법, 문의처 우선 추출
3. 본문출력파일 파싱: HTML 누락 보강
4. 첨부파일 파싱: 제출서류, 유의사항, 제외조건, 세부 지원금액 보강

## 7. 권장 유형화 틀
- 문서구조유형: html_plus_print / hwp_core / pdf_core / bundle_package / mixed_attachment
- 지원유형: funding / consulting / commercialization / startup / facility / education_event / other
- 대상유형: small_business / startup_venture / sme / social_enterprise / other
- 접수유형: website / email / visit / post / fax / mixed / other
- 기간유형: date_range / always_open / budget_exhausted / announced_later / varies_by_program / other
