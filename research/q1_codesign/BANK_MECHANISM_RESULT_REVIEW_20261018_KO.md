# Bank-Aware Channel Permutation: 병목 원인 분석 결과 및 Q1 리뷰어 판정

**실험:** BSD68 clean image 68 × AWGN σ={15,25,50} × noise seed={0,1,2} = **612 image-conditions**, 8개 대상 레이어 Conv2~9 × 612 = **4,896 row**. 이미지별/레이어별 원자료 4,896개, σ별/레이어별 요약 24개 셀의 합산을 재검증함. 원자료 경로는 GPU PC `C:\fpga\FPGA\build\q1_gpu_bank_mechanism\`이다.

**업로드된 근거:** `per_image_layer.csv`, `sigma_layer_bottlenecks.csv`, `summary.json`, `run_config.json` (2026-10-18). 신규 FPGA 하드웨어 실측은 **없다**. 다음 수치는 오직 W4 Sparse core **Conv2~9 analytical window cycle coefficients**이다.

## 1. 최종 검증

| 항목 | 집계 |
|---|---:|
| 모든 σ·seed별 이미지 수 | 68 |
| 전체 image conditions | 612/612 |
| 대상 Conv | Conv2~9, 8개 |
| Per-layer records | 4,896/4,896 |
| 요약 σ×레이어 cells | 24/24 |
| 대상 window evaluations | 189,969,696 |
| CSV duplicate image/σ/seed/layer key | 0 |
| CSV missing value | 0 |
| 24-cell summary matched against raw CSV | 24/24 |

## 2. 비용 모델의 총합 및 Optimistic lower bound

```
identity sum:    17,376,731,887 window-cycle units
frozen sum:      15,617,390,000 window-cycle units
multi sum:       15,515,883,224 window-cycle units
relaxed oracle:  14,626,058,239 window-cycle units
```

| 배치/이론치 | Baseline 대비 예상 계산 비용 감소 |
|---|---:|
| Frozen | 10.124700% |
| Multi-start | **10.708853%** |
| 윈도우별 Bank별 nonzero tap을 자유롭게 분배하는 이상적 Relaxation | **15.829637%** |

Multi-start는 이 매우 낙관적인 Relaxed oracle의 개선 여지 **67.65%**를 확보한다. 차이 **5.120784%p**는 완화된 가상의 하한 기준 남은 가능 영역이지, 실제 정적 순열로 달성 가능한 추가 속도 향상을 의미하지 않는다.

**다른 GPU 결과와 교차 검증 성공:** 앞서 보고한 10.124700% / 10.708853%가 원본 레이어 비용 집계에서도 그대로 재현된다.

## 3. σ별 예상 비용 절감과 Floor-limited window 비율

| AWGN σ | Frozen | Multi-start | Relaxed oracle bound | Baseline floor-limited | Multi floor-limited |
|---:|---:|---:|---:|---:|---:|
| 15 | 7.007236% | **8.264314%** | 12.676606% | 29.502% | 42.078% |
| 25 | 8.779397% | **9.524899%** | 14.141089% | 18.294% | 32.722% |
| 50 | **14.037079%** | 13.891984% | 20.079538% | 1.807% | 6.519% |

**물리적 원인에 관한 해석 (코어 모델 내부에서만):**
- 해당 코어 모델은 `max(feed/input floor, max-bank nonzero issue cost, output floor)`라는 병목 구조를 갖는다.
- 활성값 nonzero bank maximum을 줄이면 issue-bound window의 비용을 낮출 수 있다.
- Floor-bound가 지배적인 window는 은행 간 채널 순열을 바꾸어도 더 줄일 수 없다.
- σ15에서는 이미 29.5%의 baseline window가 floor-dominated인데 σ50에서는 약 1.8%에 불과하다. 따라서 σ50에서는 보통 더 많은 개선 여지가 생기지만, 어떤 순열이 좋은지는 데이터 분포에 따라 달라진다.

## 4. 레이어별 Multi-start 기여도 (3σ 합산)

| Layer | Baseline 대비 레이어 비용 감소율 | 전체 Multi-start 절감량 중 기여 |
|---|---:|---:|
| Conv2 | 8.2602% | 9.8657% |
| Conv3 | 9.3883% | 10.8994% |
| Conv4 | 13.1222% | 15.3994% |
| Conv5 | 14.9980% | **18.4542%** |
| Conv6 | 9.8055% | 11.1714% |
| Conv7 | **0.9288%** | **0.9783%** |
| Conv8 | 10.1385% | 11.1170% |
| Conv9 | **17.1473%** | **22.1146%** |

Conv9+Conv5는 예상 절감 총량의 **40.5688%**를 담당한다. Conv7는 다른 레이어와 크게 달리 성능 향상이 거의 없다.

### 위험 사례: σ=50 / Conv7

- Frozen Conv7 예상 비용 변화: **−2.233297%** (값이 음수 = 오히려 비효율).
- Multi-start Conv7 예상 비용 변화: **−4.265063%**.
- Multi-start의 204 image-seed conditions 중 **201개에서 Conv7만 따로 보면 비용이 증가**한다 (개선 3개).
- Conv7 mean max-bank nonzero count는 identity **42.4514**, Frozen **43.3879**, Multi-start **44.2598**.
- 해당 악화가 있어도 Conv2~9 합산은 모든 612 input conditions에서 identity보다 개선. 대신 σ50에서 Frozen이 Multi보다 낫다는 이전 분석 결과와 정합적이다.

따라서 **'모든 레이어·입력에서 개선'이라는 주장은 절대 금지**. 정확한 주장은 대상 Conv2~9 **합산**의 예상 비용이 연구에 사용된 612개 입력 조건에서 모두 감소했다는 것이다.

## 5. Q1 리뷰어 공격의 대응 가능성과 한계

**Reviewer 공격 A: 왜 계산 비용이 감소하는가?**
- 답변 가능: 입력 윈도우별 최대 Bank nonzero 작업량이 동기식 코어 issue 병목을 결정하고, 순열은 이를 바꾼다. floor-bound window를 함께 정량화함.
- 핵심 수치: σ15 floor-bound 29.502% vs σ50 1.807%; Conv9 17.147% 개선; σ50 Conv7은 오히려 4.265% 악화됨.

**Reviewer 공격 B: 얼마나 최적에 가까운가?**
- 매우 느슨한 이론 하한 관점의 개선 여지 15.830% vs 실현된 분석적 10.709%. 완화 문제의 상한 성취 67.65%를 기술할 수는 있으나 **정적 채널 배치의 최적성 비율/approximation guarantee로 해석하면 안 됨**.

**Reviewer 공격 C: 분포가 바뀌어도 항상 좋은가?**
- **아니오**. 특정 레이어에서 악화가 존재하며, σ50에서는 Frozen과 Multi-start의 우위가 역전된다. 입력 변화에 강건한 layout을 새로운 연구 가설로 검토할 수 있지만, BSD68의 σ50 결과를 보고 다시 선정하면 데이터 누수 위험.
- σ15·25·50은 동일 sigma25-trained QAT CNN의 activation distribution 변화 분석이지 잡음별 재학습 비교는 아님.

**Reviewer 공격 D: 진짜 FPGA 성능이 같은가?**
- **미검증.** 이 보고서는 그 메커니즘을 설명하는 모델 기반 증거지, 실제 코어의 병목 원인까지 실측으로 검증한 게 아니다. 실제 보드 layer-by-layer cycles/IN_STALL/OUT_STALL을 측정해 모델 예측 방향 및 원인을 검증할 필요가 있다.

**Reviewer 공격 E: 기존 기술과 얼마나 다른가?**
- 현재 결과만으로 새로운 channel permutation/load balancing 알고리즘이 탄생했다고 볼 수 없다. Fair-budget에서 Multi-start가 본질적으로 우수하다는 주장도 지지되지 않았다.
- 우선 신규성 후보는 `기존 fixed W4 sparse FPGA core의 window-level max-bank active workload와 floor bottleneck을 사용하는 기능 보존형 static channel layout selection`이며, 별도로 선행연구 대비해야 한다.

## 6. 다음 실행 및 저장 위치

1. **GPU 분석은 본 메커니즘 연구까지 완료**. 비슷한 조건으로 반복 추론을 더 돌리기보다 물리 FPGA A/B/C를 우선한다.
2. **FPGA PC에서 보드 비파괴 사전 점검:** `RUN_FPGA_Q1_TRIPLET_PREFLIGHT.cmd`.
3. **Smart ZYNQ SL 보드의 PS DDR/MIO, 실제 pinout/clock, W4 bitstream을 직접 검증**한 뒤 `RUN_FPGA_Q1_TRIPLET.cmd`로 Original/Frozen/Multi 3종 × 3회.
4. **실측 출력 위치(실행 후):** `C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json` 및 `triplet_summary.md` (FPGA PC 저장소가 위 경로에 있을 때).
5. 본 문서의 GitHub 위치: `research/q1_codesign/BANK_MECHANISM_RESULT_REVIEW_20261018_KO.md`.
6. GPU 원본 결과는 GitHub 문서에 전부 업로드한 것이 아니라 GPU PC의 `build\q1_gpu_bank_mechanism\{per_image_layer.csv,sigma_layer_bottlenecks.csv,summary.json,run_config.json}`에 그대로 유지한다.

**최종 판정: "하드웨어가 왜 빨라져야 하는가"의 분석적 근거는 상당히 구체화됐다. 하지만 FPGA에서 같은 병목 모델이 실측으로도 성립하고, 선행연구 대비 유의미한 기여라는 점은 아직 미검증이다.**
