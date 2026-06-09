# 클로드 검증용 핸드오프: 정책상품 ML 분류 실험과 중복 사전 배치

- 작성일: 2026-06-02
- 프로젝트: `C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745`
- 목적: 현재까지 도출한 방법론과 실행 결과를 클로드가 독립적으로 재현하고 비판적으로 검증할 수 있도록 정리한다.

## 1. 먼저 확인할 결론

현재 완료된 것은 **정책공고 지식DB 구축**과 **ML 분류 실험을 위한 중복·반복사업 사전 배치**이다.

아직 완료되지 않은 것은 `LCA`, `Gower distance + PAM`, 계층형 군집화, 문장 임베딩 군집화를 실제로 실행하고 최적 모형을 고르는 단계이다. 이 핸드오프는 완료된 결과와 다음 구현 사양을 의도적으로 분리한다.

현재 산출물 요약:

| 항목 | 값 |
|---|---:|
| 원본 정책공고 | 795 |
| 자동 삭제 | 0 |
| ML 입력 대표 공고 | 795 |
| 내용 반복 검토 그룹 | 2 |
| 복수 공고 사업군 | 16 |
| 사업군 포함 공고 | 54 |
| 유사도 기반 추가 검토 후보 | 157 |

## 2. 방법론이 도출된 과정

### 2.1 연구 프레이밍

처음 문제는 정책공고를 구조화하는 파서였다. 문헌 검토 후 문제를 다음처럼 확장했다.

> 정책상품 속성 지식베이스를 구축하고, 데이터 기반 taxonomy와 설명 가능한 정책 탐색·추천을 설계한다.

정책공고는 전자상거래의 상품과 완전히 같지는 않다. 그러나 `금액`, `금리`, `대상`, `제외조건`, `신청방법`, `필요서류`, `지원목적`을 속성으로 갖고, 탐색·비교·추천이 필요하다는 점에서 상품 taxonomy 연구와 연결할 수 있다.

### 2.2 사람이 정답을 부여하지 않는 분류 실험

전문가 라벨 없이 분류체계를 탐색하려면 하나의 ML 기법을 미리 정답으로 정하면 안 된다. 동일한 데이터에 복수의 비지도 방법을 적용하고, 구조적 일관성과 재현성을 같은 지표로 비교해야 한다.

비교 후보:

| 방법 | 입력 | 목적 |
|---|---|---|
| `LCA` | 범주형 정책 속성 | 잠재 정책유형 탐색 |
| `Gower distance + PAM` | 범주형·수치형 혼합 속성 | 대표 정책 중심 군집 |
| `Gower distance + hierarchical clustering` | 혼합 속성 | 계층형 taxonomy 후보 |
| `sentence embedding + clustering` | 공고 요약 텍스트 | 구조화 속성에서 놓친 의미에 대한 민감도 분석 |

공통 평가:

| 평가 축 | 지표 | 해석 |
|---|---|---|
| 응집도·분리도 | `Silhouette`, `Davies-Bouldin`, `Calinski-Harabasz` | 같은 군집은 가깝고 다른 군집은 먼지 비교 |
| 재표집 안정성 | `Bootstrap Jaccard` | 표본을 바꿔도 군집이 유지되는지 비교 |
| 기관·연도 재현성 | `ARI`, `NMI` | 하위 표본에서도 구조가 유지되는지 비교 |
| LCA 모형 선택 | `BIC`, `entropy`, `BLRT` | 잠재 집단 수 `k` 비교 |
| 반복사업 영향 | 가중·비가중 결과 비교 | 반복사업이 결론을 왜곡하는지 비교 |

중요한 제한:

- 이 평가는 행정적·법적 정답을 증명하지 않는다.
- 이 평가는 taxonomy 후보가 데이터에서 반복적으로 관찰되는 구조인지 검증한다.
- 절대 합격선이 없는 지표는 같은 데이터에서 후보 모형을 상대 비교한다.
- `Bootstrap Jaccard`는 `0.75 이상`을 권장 기준, `0.85 이상`을 안정적인 군집의 참고 기준으로 둔다.

### 2.3 동일·유사 공고를 먼저 배치한 이유

같은 사업이 지역별, 기관별, 회차별로 반복되면 ML은 반복 횟수를 독립적인 정책유형의 증거로 오해할 수 있다. 학습·검증 데이터에 같은 사업군이 동시에 들어가면 성능도 부풀려진다.

따라서 원본을 삭제하지 않고 다음 필드를 부여했다.

| 필드 | 의미 |
|---|---|
| `publication_group_id` | 확실한 동일 공고의 대표 통합 단위 |
| `content_repeat_group_id` | 구조화 내용이 같지만 자동 삭제하지 않은 검토 단위 |
| `program_family_id` | 지역·회차·기관별 반복사업 묶음 |
| `split_group_id` | 학습·검증 분할 시 함께 움직일 사업군 ID |
| `family_weight` | 반복사업 과대대표를 줄이는 `1 / 사업군 크기` 가중치 |

현재 DB에서는 의미 손실 없이 자동 통합할 수 있다고 확정한 공고가 없었다. 특히 일반 스마트공장 공고와 `AI트랙` 공고는 추출 필드가 비슷해도 의미 차이가 있을 수 있어 자동 삭제하지 않았다.

## 3. 현재 파일

| 역할 | 파일 |
|---|---|
| 원본 구조화 DB | `outputs\knowledge-db.json` |
| 추출 요약 리포트 | `outputs\knowledge-db-report.html` |
| 사전 배치 결과 | `outputs\ml-preallocation.json` |
| ML 분석용 배치표 | `outputs\ml-preallocation.csv` |
| 사전 배치 계획서 | `outputs\ml-taxonomy-experiment-plan-20260602.html` |
| 지식DB 구축 | `scripts\build-knowledge-db.py` |
| 중복·사업군 사전 배치 | `scripts\build-ml-preallocation.py` |
| 사전 배치 독립 검증 | `scripts\validate-ml-preallocation.py` |
| 일괄 검증 명령 | `scripts\claude-validation-commands.ps1` |

## 4. 클로드가 바로 실행할 명령

PowerShell에서 다음 한 줄을 실행하면 현재 산출물 검증, 격리 폴더 재생성, 해시 비교까지 수행한다.

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745\scripts\claude-validation-commands.ps1"
```

개별 Python 명령은 아래와 같다.

### 4.1 환경 확인

```powershell
cd "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745"
python --version
python -c "import importlib.util; names=['numpy','pandas','scipy','sklearn','statsmodels']; print({n: bool(importlib.util.find_spec(n)) for n in names})"
```

현재 확인한 Python 버전은 `3.11.9`이다.

### 4.2 기존 지식DB 회귀 테스트

```powershell
python -m unittest discover -s ".\tests" -p "test_*.py" -v
```

현재 결과는 `8 tests / PASS`이다.

### 4.3 공식 사전 배치 산출물 독립 검증

```powershell
python ".\scripts\validate-ml-preallocation.py" `
  --knowledge-db ".\outputs\knowledge-db.json" `
  --allocation-json ".\outputs\ml-preallocation.json" `
  --allocation-csv ".\outputs\ml-preallocation.csv"
```

검증 항목:

- `knowledge-db.json`의 795개 ID가 JSON·CSV에 빠짐없이 존재하는가
- ID가 중복되지 않는가
- `split_group_id == program_family_id`인가
- `program_family_size`, `publication_group_size`가 실제 그룹 크기와 같은가
- `family_weight == 1 / program_family_size`인가
- 요약 통계가 실제 레코드에서 다시 계산한 값과 같은가
- 입력과 산출물의 SHA-256 해시가 무엇인가

### 4.4 격리 폴더에서 사전 배치 재생성

```powershell
New-Item -ItemType Directory -Force ".\outputs\_claude-validation" | Out-Null

python ".\scripts\build-ml-preallocation.py" `
  --input ".\outputs\knowledge-db.json" `
  --output-dir ".\outputs\_claude-validation"

python ".\scripts\validate-ml-preallocation.py" `
  --knowledge-db ".\outputs\knowledge-db.json" `
  --allocation-json ".\outputs\_claude-validation\ml-preallocation.json" `
  --allocation-csv ".\outputs\_claude-validation\ml-preallocation.csv"
```

### 4.5 공식 산출물과 재생성 산출물 비교

```powershell
Get-FileHash ".\outputs\ml-preallocation.json", ".\outputs\_claude-validation\ml-preallocation.json" -Algorithm SHA256
Get-FileHash ".\outputs\ml-preallocation.csv", ".\outputs\_claude-validation\ml-preallocation.csv" -Algorithm SHA256
```

해시가 같으면 사전 배치가 결정론적으로 재현된 것이다.

### 4.6 검토 후보 확인

```powershell
python -c "import json, pathlib; d=json.loads(pathlib.Path(r'.\outputs\ml-preallocation.json').read_text(encoding='utf-8')); print(json.dumps(d['contentRepeatCandidates'], ensure_ascii=False, indent=2))"

python -c "import json, pathlib; d=json.loads(pathlib.Path(r'.\outputs\ml-preallocation.json').read_text(encoding='utf-8')); print(json.dumps(d['programFamilies'][:20], ensure_ascii=False, indent=2))"

python -c "import json, pathlib; d=json.loads(pathlib.Path(r'.\outputs\ml-preallocation.json').read_text(encoding='utf-8')); print(json.dumps(d['fuzzyReviewCandidates'][:30], ensure_ascii=False, indent=2))"
```

## 5. 전체 데이터 파이프라인 재생성 명령

다음 명령은 공식 `outputs` 파일을 다시 생성한다. 현재 결과를 보존해야 한다면 폴더를 먼저 복사하거나 Git 변경 상태를 확인한 후 실행한다.

```powershell
cd "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745"

python ".\scripts\analyze-field-coverage.py"
python ".\scripts\normalize-notices.py"
python ".\scripts\build-knowledge-db.py"

python ".\scripts\build-ml-preallocation.py" `
  --input ".\outputs\knowledge-db.json" `
  --output-dir ".\outputs"

python ".\scripts\validate-ml-preallocation.py" `
  --knowledge-db ".\outputs\knowledge-db.json" `
  --allocation-json ".\outputs\ml-preallocation.json" `
  --allocation-csv ".\outputs\ml-preallocation.csv"
```

보조 질의 테스트:

```powershell
python ".\scripts\sample-query-test.py"
```

## 6. 다음 구현 단계의 명령 사양

아래 명령은 **아직 실행할 수 없다**. `scripts\run-ml-taxonomy-benchmark.py`를 다음 단계에서 구현할 때 지켜야 할 CLI 계약이다.

```powershell
python ".\scripts\run-ml-taxonomy-benchmark.py" `
  --knowledge-db ".\outputs\knowledge-db.json" `
  --preallocation ".\outputs\ml-preallocation.csv" `
  --algorithms "lca,pam,hierarchical,embedding" `
  --k-min 4 `
  --k-max 20 `
  --bootstrap 1000 `
  --seed 20260602 `
  --weight-column "family_weight" `
  --split-group-column "split_group_id" `
  --output-dir ".\outputs\ml-taxonomy-benchmark"
```

반드시 생성해야 할 결과:

| 결과 | 내용 |
|---|---|
| `model-comparison.csv` | 알고리즘·`k`별 공통 지표 |
| `cluster-stability.csv` | bootstrap Jaccard |
| `weighted-vs-unweighted.csv` | 반복사업 가중치 적용 전후 비교 |
| `subsample-reproducibility.csv` | 기관·연도 하위 표본의 ARI·NMI |
| `cluster-assignments.csv` | 공고별 군집 배정 |
| `benchmark-report.html` | 선택 근거와 한계 |

## 7. 클로드에게 요청할 검증 질문

1. `publication_group_id`, `content_repeat_group_id`, `program_family_id`의 경계가 지나치게 보수적이거나 느슨하지 않은가?
2. 동일 사업군이 train·validation에 동시에 들어가지 않도록 `split_group_id`를 사용하는 설계가 충분한가?
3. `family_weight = 1 / n` 민감도 분석이 반복사업의 과대대표 문제를 다루기에 적절한가?
4. 범주형·수치형 혼합 정책 데이터에 `LCA`, `Gower + PAM`, 계층형 군집화 비교가 적절한가?
5. 문장 임베딩 군집화는 주 모형이 아니라 민감도 분석으로 두는 것이 타당한가?
6. 평가 지표와 보고 범위에서 빠진 통계적 검증이 있는가?
7. 전문가 라벨 없이 주장할 수 있는 범위를 구조적 일관성과 재현성으로 제한한 것이 적절한가?

## 8. 방법론 참고문헌

- Rousseeuw, P. J. (1987). Silhouettes: A graphical aid to the interpretation and validation of cluster analysis. <https://doi.org/10.1016/0377-0427(87)90125-7>
- Hennig, C. (2007). Cluster-wise assessment of cluster stability. <https://www.sciencedirect.com/science/article/pii/S0167947306004622>
- Ben-Hur, A., Elisseeff, A., & Guyon, I. (2002). A stability based method for discovering structure in clustered data. <https://psb.stanford.edu/psb-online/proceedings/psb02/benhur.pdf>
- Nylund, K. L., Asparouhov, T., & Muthén, B. O. (2007). Deciding on the number of classes in latent class analysis. <https://doi.org/10.1080/10705510701575396>
- Hao, Y., Shen, Y., Ni, J., & Torzec, N. (2021). An evaluation and annotation methodology for product category matching in e-commerce. <https://www.sciencedirect.com/science/article/pii/S0166361521001044>

## 9. 검증 시 주의할 표현

가능한 주장:

> 복수의 비지도 분류 방법을 비교하고 반복사업의 영향을 통제한 결과, 선택한 정책상품 taxonomy 후보는 응집도, 분리도, 재표집 안정성, 하위 표본 재현성 측면에서 일관된 구조를 보였다.

현재 단계에서 하면 안 되는 주장:

> 정책상품 taxonomy가 행정적으로 완벽하게 옳다는 것이 입증되었다.

전문가 정답 라벨 없이 검증할 수 있는 것은 구조적 일관성과 재현성이다. 법적·행정적 적합성은 별도의 검증 범위다.
