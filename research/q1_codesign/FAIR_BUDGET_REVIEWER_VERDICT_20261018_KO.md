# Q1 적대적 리뷰어 대응: FAIR BUDGET 실제 결과 및 판정

**실험 종료 확인:** 2026-10-18. 원자료: 사용자가 업로드한 \`run_config.json\`, \`summary(3).json\`, \`per_image.csv\`, \`method_summary.csv\`, \`fair_paired.csv\`, \`search_effort.csv\`, \`search_groups.json\`. 이 보고서는 실제 데이터의 별도 재집계로 작성했으며 아직 새로운 FPGA 실측은 없다.

## 0. 판정 요약

> **기존의 "Multi-start Greedy는 다른 최적화 알고리즘보다 본질적으로 더 우수하다"는 주장은 동일 탐색 예산 실험으로 뒷받침되지 않는다.**
>
> **하드웨어의 4-bank 최대 비영 활성화 부하를 줄이는 정적 채널 순열 최적화 자체는 여전히 유효한 연구 방향이다.**
>
> 적대적 리뷰어 대응에서는 **알고리즘 우위가 아니라 기능 보존형 배치 변경과 실제 FPGA 병목 완화 원리**를 핵심 기여 후보로 삼아야 한다.

## 1. 실험 설계 무결성

- QAT CNN: \`dn_d10_c32_us_fx_qat\`.
- Calibration 데이터: 동일 Set12 01/02/03, sigma25, noise seeds 0/1; 각 레이어별 6,144 sampled activation windows.
- Test: BSD68 68개 원본 이미지 × sigma15/25/50 × noise seed0/1/2 = **612 image-condition**.
- 탐색 알고리즘: 단일 Greedy, Simulated Annealing, 5-start Multi-start Greedy.
- 목적함수 평가 예산: **400/800/2,000**, 초기 해 평가를 포함해 동일.
- Optimizer seeds: **42/101/202/303/404**.
- 고정 대조군: identity, frozen_01. 총 방법-예산-시드 조합 3×3×5=45, plus 2 controls=47.
- 검증된 결과 행: **612×47 = 28,764**, 중복 이미지·잡음·방법 없음.
- 탐색 로그: 360개 레이어×방법 설정; 실제 \`cost_evaluations\`은 모든 레이어 및 모든 시드에서 지정 예산과 일치.
- \`saved_pct\`와 원본/최적 비용의 직접 재계산 최대 오차 약 **5e-9%p**.
- 모든 612개 입력 조건에서 방법 간 baseline core cycles가 동일함.
- 비용 모델은 **Conv2~9의 W4 Sparse core window 추정 사이클**, FPGA 실측은 아님.

## 2. 알고리즘별 5시드 평균: 주 비교 결과

| 예산 (objective evaluations) | Greedy mean | Anneal mean | Multi-start mean | Multi − Greedy (pp) | Multi − Anneal (pp) |
|---|---:|---:|---:|---:|---:|
| 400 | **10.43503%** | 10.39439% | 9.81162% | **−0.62341** | **−0.58277** |
| 800 | **10.44228%** | 10.42348% | 10.32006% | **−0.12222** | **−0.10342** |
| 2000 | 10.57016% | 10.55107% | **10.64277%** | **+0.07260** | **+0.09170** |

표의 각 셀은 **5개 optimizer seed로 따로 보정한 순열을 BSD68 동일 612 image-condition에서 평가한 core proxy 감소율의 평균**이다. 612는 독립 clean image 개수가 아니라 68개 이미지의 9개 잡음 조건 반복측정이다.

### 우승 횟수 (각 예산 × 시드마다 3종 중 최고)

- **400회:** Greedy 3/5, Anneal 2/5, Multi-start 0/5.
- **800회:** Greedy 3/5, Anneal 1/5, Multi-start 1/5.
- **2000회:** Greedy 0/5, Anneal 2/5, Multi-start 3/5.

동일 예산에서 Multi-start가 항상 우수하다는 강한 주장은 불가능하며, 예산이 작은 구간에서는 명백히 불리하다.

### Seed-level paired difference와 불확실성

| 예산 | Multi − Greedy: 5-seed 평균(%)p | 시드 기반 95% Student-t 구간(%)p | Multi가 Greedy보다 유리한 seed |
|---|---:|---|---:|
| 400 | −0.62341 | [−0.81771,−0.42912] | 0/5 |
| 800 | −0.12222 | [−0.68867,+0.44424] | 2/5 |
| 2000 | +0.07260 | [−0.37077,+0.51598] | 4/5 |

| 예산 | Multi − Anneal: 5-seed 평균(%)p | 시드 기반 95% Student-t 구간(%)p | Multi가 Anneal보다 유리한 seed |
|---|---:|---|---:|
| 400 | −0.58277 | [−1.01237,−0.15317] | 0/5 |
| 800 | −0.10342 | [−0.41283,+0.20599] | 2/5 |
| 2000 | +0.09170 | [−0.41290,+0.59630] | 3/5 |

**주의:** 이 구간은 불확실성에 대한 간략한 탐색적 5시드 계산이다. 표본이 작고 평가 데이터 선택 이력이 있으므로 일반적 모집단에 대한 확정적 신뢰구간/유의성 주장 금지. 기존 \`fair_paired.csv\`의 *이미지별* bootstrap 구간은 개별 optimizer seed를 조건으로 한 구간이어서 **optimizer seed 불확실성을 포함하지 않는다**. 같은 사진 68장을 많이 반복했다고 시드 효과가 사라지는 것은 아니다.

## 3. 반례: 400회 단일 Greedy가 기존 Multi-start 배치보다 우수

- \`greedy_B400_O42\` = **10.908098%** predicted gain.
- 종전에 배포했던 별도 calibration 설정의 \`multistart_greedy\` = **10.708853%** predicted gain.
- \`multistart_B2000_O42\` = **10.974091%**, 그러나 시드42가 모든 시드에서 최선이라는 보장은 없고, BSD68 성능으로 최고 seed를 사후 선택하면 **evaluation leakage**이다.
- 종전 \`frozen_01\` = **10.124700%**, 하지만 원래 Frozen과 신규 3방법은 Calibration 집합이 달라 알고리즘 효과를 직접 비교하는 matched baseline은 아니다.

**추가 중요한 징후:** Greedy의 같은 optimizer seed=42에서 B400→B800 모델의 BSD68 추정 개선율은 10.9081%→10.4197%로 떨어졌다. 해당 Greedy는 Calibration objective가 예산 증가 시 개선되도록 구성되어 있으므로, 이 역전은 Calibration proxy 최적화 향상과 평가 집합의 성능 향상이 항상 일치하지 않음을 시사한다. 특정 holdout에서 이득이 큰 후보를 마음대로 골라 새 챔피언으로 사용하면 선택편향을 더 강화한다.

### CPU 최적화 시간 비교

각 레이어×optimizer seed에서의 평균 소요시간:

| Objective 평가 예산 | Greedy | Anneal | Multi-start |
|---|---:|---:|---:|
| 400 | 0.117초 | 0.117초 | 0.118초 |
| 800 | 0.230초 | 0.231초 | 0.232초 |
| 2000 | 0.589초 | 0.588초 | 0.590초 |

실제 오프라인 계산 시간에서도 세 방법은 거의 동일한 예산을 사용했다. 단, 이 값은 CPU에서 수행한 탐색 연산시간이고 GPU 추론이나 FPGA 추론 시간이 아니다.

## 4. 잡음 분포와 탐색 예산의 교차효과

5 최적화 seed를 묶어 각 sigma별 비용의 합에서 계산:

| 예산 | Sigma | Greedy (%) | Anneal (%) | Multi-start (%) |
|---|---|---:|---:|---:|
| 400 | 15 | 7.915 | **7.992** | 7.727 |
| 400 | 25 | 9.208 | **9.212** | 8.978 |
| 400 | 50 | **13.722** | 13.539 | 12.369 |
| 800 | 15 | **8.033** | 8.018 | 7.929 |
| 800 | 25 | 9.466 | **9.489** | 9.310 |
| 800 | 50 | **13.409** | 13.350 | 13.301 |
| 2000 | 15 | 8.211 | **8.319** | 8.207 |
| 2000 | 25 | **9.671** | 9.572 | 9.614 |
| 2000 | 50 | 13.425 | 13.366 | **13.680** |

이 결과는 기존 “Multi-start가 sigma50에서 Frozen보다 불리하다”라는 개별 배치 결과와 모순되지 않는다. **선택된 채널 배치·calibration 설정·optimizer seed가 다르기 때문**이다. “Noise-aware automatically optimal” 같은 문구 사용 금지.

## 5. Q1 적대적 리뷰어 관점 판정

### 반드시 철회해야 하는 주장

- “Multi-start Greedy는 동일 탐색 예산으로 Greedy나 Annealing보다 명확히 우수하다.”
- “Multi-start 10.709%는 알고리즘 신규성 또는 우월성을 증명한다.”
- “이미지 bootstrap 신뢰구간이 좁으므로 최적화 시드에 따른 성능 변동도 작다.”
- “GPU core cycle proxy 감소가 FPGA 실측 throughput 개선을 의미한다.”

### 지킬 수 있는 주장

- 동일 모델·동일 입력·동일 calibration budget에서 **Greedy/Anneal/Multi-start 3개 모두 상당한 W4 sparse core 비용 감소**를 얻었다.
- Multi-start는 높은 탐색 예산에서 평균이 소폭 유리할 수 있으나, 최적화 시드·예산에 민감하므로 **여러 검색 전략 중 하나**로만 보고한다.
- 정수 출력 보존형 채널 순열은 탐색 방법 선택과 별개의 구현상 결과다.
- **연구의 핵심은 synchronous bank-max workload bottleneck의 분석적 정식화 및 FPGA에서의 직접 검증**이어야 한다.

### 다음 필수 작업

1. GPU PC: \`RUN_GPU_Q1_BANK_MECHANISM.cmd\` 실행 — 레이어×sigma의 floor-bound 비율과 max-bank 감소를 통해 원인 설명.
2. FPGA PC: \`RUN_FPGA_Q1_TRIPLET_PREFLIGHT.cmd\`만 먼저 실행, Smart ZYNQ SL PS DDR/MIO/bitstream을 독립 검증한 뒤에만 실측 3모델×3회.
3. 다른 test clean image set 또는 train/calibration 분리 프로토콜로 optimizer seed 및 budget을 **BSD68에서 사후 선택하지 않고** 평가.
4. 논문 기여는 “Multi-start superiority” 대신 “function-preserving activation-bank scheduling on a fixed sparse W4 FPGA accelerator”의 적용 조건, cost model fidelity, 실제 hardware outcome으로 재구성.

## 6. 한 문장 요약

**공정한 5시드 × 3예산 결과, Multi-start는 저예산에서 일관되게 불리하고 2,000회에서만 평균 0.073%p 유리하나 불확실성 구간이 0을 포함한다. 기존 10.709% 성과는 구현 배치의 결과이지 최적화 알고리즘 우월성의 증거가 아니다.**
