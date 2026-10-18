# GPU 종합 실험: 2026-10-18 확보 결과와 최종 연구 판정

> 근거: 사용자 GPU PC의 `build/q1_gpu_deadline_final/EVIDENCE_REPORT_KO.md` 업로드 내용 (요약 보고서 기반). 개별 CSV 또는 하드웨어 로그를 본 문서 작성 시 직접 독립 검증하지 않았음.

## 1. 완료 상태

- 기존 frozen channel permutation, BSD68 68/68 개선 (sigma25 / noise seed0, W4 sparse core coefficient)
- 원본 vs 재배열 ReLU QAT 출력 일치: BSD68 68/68, 0픽셀 차이
- 종합 optimizer-benchmark: **5,508 / 5,508 method-image rows**
- CNN 아키텍처 전이: ReLU 64ch **408 / 408** 이미지·조건; Maxout 32ch **408 / 408** 이미지·조건
- Multi-sigma/multi-seed bit-exact: Set12+BSD68 **720 / 720** 이미지·조건, **0** 최종 출력 불일치
- **새로운 재배열 모델을 FPGA W=4에서 직접 실측한 데이터는 아직 없음**

## 2. 주요 모델: 알고리즘 비교

| 방법 | 3 Sigma×3 noise seeds 통합, W4 sparse Conv2~Conv9 분석 계수 감소율 |
|---|---:|
| identity | 0.000% |
| frozen_01 (기존 고정 후보) | 10.125% |
| density_sort | 2.703% |
| greedy | 10.389% |
| anneal | 10.513% |
| **multistart_greedy** | **10.709%** |
| risk_aware_greedy | 10.295% |
| random_mean | -1.200% |
| random_best_reference | 3.496% |

각 방법은 원본과 **동일한 입력 영상**, **동일한 CNN 가중치**, **동일한 W4 코어 비용 모델**에서 비교.
`random_best_reference`는 각 평가 영상에서 무작위 후보 중 최선을 사후 선택하는 비배포 가능 대조군. 다른 optimizer보다 우월한 '상한'이라는 의미는 아님.

`multistart_greedy`는 통합 평균에서 `frozen_01`보다 **0.584 percentage points** 더 줄임. 유의성 주장은 금지: `RUN_GPU_Q1_PAIRED_STATS.cmd`로 68개 이미지 단위 paired cluster bootstrap 필요.

## 3. Sigma별 교차되는 최선

| sigma | frozen_01 | multistart_greedy | 관찰된 우위 |
|---|---:|---:|---|
| 15 | 약 7.01% | 약 8.26% | Multi-start |
| 25 | 약 8.78% | 약 9.53% | Multi-start |
| 50 | 약 14.04% | 약 13.89% | Frozen |

Sigma50에서 frozen의 예상 이득이 더 커지므로 모든 조건에 Multi-start가 압도적으로 최적이라는 진술은 오류.

특히 sigma별 가장 좋은 배치를 테스트 이미지의 sigma별 진실값으로 사후 선택하면 leakage가 됨. 입력의 sigma를 사전에 알고 있는 합법적 조건인지, sigma estimator를 별도로 사용할 것인지, 실제 end-to-end 이득이 여전한지 구분 필요.

## 4. 추가 CNN 전이 (Virtual only)

| 네트워크 | Density | Greedy | Anneal | Multi-start |
|---|---:|---:|---:|---:|
| 64ch ReLU QAT | 6.569% | 9.813% | 9.878% | **9.946%** |
| Maxout QAT | 0.833% | 4.022% | 3.954% | **4.237%** |

**주의:** 이는 정수 CNN의 중간 활성값에서 계산한 뱅크 그룹 비용 *예측*이며, 64ch/Maxout용 재배열 Export가 실제로 준비되어 출력 일치 0으로 확인됐다는 뜻이 아님. Maxout의 paired output channel permutation은 특히 별도 export·full image bitexact가 필요.

## 5. 현재 Q1 논문 판정 (reviewer-style)

| 축 | 평가 |
|---|---|
| 근거 데이터 규모 | 개선: 3 sigma×3 noise draws, 68 BSD68 + 2개 보조 QAT CNN |
| 기존 알고리즘 대비 비교 | Greedy, Anneal, Multi-start, Density, Random까지 가능 |
| 수치 안정성 | 주요 결과가 다양한 noise seed에서 유지; 통계적 paired-difference CI 미산출 |
| 출력 품질 | 32ch ReLU QAT 720이미지-조건 전수 픽셀 출력 일치 |
| 실제 FPGA | **재배열 모델 실측 0**, CPU 비용 추정에 머물러 있음 |
| novelty | **현재 부족**, 채널 순열·Sparse bank balancing 선행연구 대비 새로운 알고리즘적 기여 정의 필요 |
| 위험 | CNN 자체의 BSD68 모델 개발 이력, Set12 calibration, 이미지 단위 상관관계, 물리 파이프라인 성능 미측정 |

## 6. 다음 실행 2개 — GitHub

### GPU PC: paired statistics (추가 CNN 추론 없음)

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_GPU_Q1_PAIRED_STATS.cmd
```

입력: `build/q1_gpu_deadline_full/per_image_methods.csv`; 출력:
`build/q1_gpu_deadline_final/PAIRED_STATS.md`,
`paired_tests.json`, `paired_tests.csv`, `method_comparison.png`.

### FPGA PC: physical A/B

1. `RUN_FPGA_Q1_BANK_PREFLIGHT.cmd`로 모델 ZIP 해시·가중치 검증.
2. **Smart ZYNQ SL PS DDR/MIO가 검증된 전용 W=4 비트스트림에서만** `RUN_FPGA_Q1_BANK_AB.cmd` 사용.
3. 원본/변형의 동일 이미지, 동일 clock 50MHz, 동일 W4 bitstream, `mode=1`, 모든 레이어 exact board oracle, `IN_STALL`, `OUT_STALL`을 함께 비교.
4. **원본 W4 코어 실측값과 새 변형 분석 모델 결과를 비교한 수치 자체를 새 FPGA 실측값으로 포장하지 말 것**.

## 7. 기한 관련

2026-10-19까지 가능한 범위에서 GPU 실험을 마무리하더라도 이는 **GPU 연구 결과의 완료**이지 'Q1 실증 논문 제출 준비 완료'라는 뜻이 아님. FPGA A/B 결과가 부정적이라면 출판 주장 대신 원인을 분석하고 모델을 개선해야 함.

