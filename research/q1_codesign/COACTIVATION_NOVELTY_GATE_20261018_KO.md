# Q1 / IF 2–3 신규성 강화 — 채널 동시활성화 정량 분리 및 공정 비교 (2026-10-18)

**상태:** 새로운 FPGA 실행을 추가한 것이 아니라, 이미 물리 검증된 Set12 05.png의 INT8 feature maps를 읽어 **새로운 오프라인 반증형 실험을 실제 수행한 결과**. 이것만으로 독립 BSD68 논문 신규성이 최종 성립한 것은 아님.

## 1. 논문에서 주장할 좁은 기여

**Proposed positioning:** *Activation co-occurrence-aware, lossless static channel-to-bank mapping for synchronized sparse INT8 convolution engines.*

기존의 channel permutation, greedy channel assignment, load balancing 자체의 신규성을 주장하지 않음. 본 연구의 좁은 강점은 **각 채널의 평균/주변 희소성만 보아서는 나타나지 않는 동기식 Bank의 윈도우별 최대 부하**를 최적화 대상으로 둔 것. 기존 INT8 모델과 기존 FPGA RTL을 바꾸지 않고 모델 재배치만 적용함.

## 2. 물리 실험 기준선 (이미 검증됨)

- Set12 05.png, sigma25, noise seed0, quantized 10-layer CNN `dn_d10_c32_us_fx_qat`.
- 동일 W4 FPGA bitstream, 50 MHz, Core ID `0x4d410303`.
- Original 13,289,030, Frozen 12,355,814, Multi-start 12,278,419 물리 cycles (대표 정상 반복).
- **Conv1–10 물리 7.60485% 절감, Conv2–9 물리 8.84855% 절감**.
- 원시 `trial_01.zip` 3반복 90개 Conv 실행 모두 integer oracle 통과; 출력 완전 보존.
- 채널별 동시 활성화를 포함하는 현 비용 모델은 같은 입력에서 물리적 절감량과 **38 cycles** 차이.
- 신규성 진단의 출처 ZIP SHA256: `3b326c80bbc46d3a16d9afe7690e085345fdd5c2eccc99cffde9f1b425076e8b`.

## 3. 신규 오프라인 실험 A: channel-wise NNZ-marginal preservation / coactivation destruction

각 Conv2–9의 실제 `trial_01/rep_01/original/05_maps10.npz`에서 32채널별 3×3 윈도우 NNZ 수 `n_c(v)` 복원.

자연스러운 윈도우에서는 동일 공간 위치에서 여러 채널이 동시에 활성화될 수 있음. **채널마다 행 순서를 독립적으로 섞으면 각 채널의 NNZ histogram은 정확히 유지하되, 채널 사이 윈도우 위치 정렬은 깨진다.** 기존 Original/Frozen/Multi-start 정적 배치를 그대로 적용하여 동일 Bank 비용 함수를 계산. 20개 정해진 randomization seed 기반 null draws, 사후 선택 없음.

| 레이어 | 실제 joint 활성화에서 Multi (%) | 채널별 histogram 유지 + 독립 셔플 (%) |
|---|---:|---:|
| Conv2 | 8.373 | 7.694 |
| Conv3 | 6.306 | 0.051 |
| Conv4 | 9.448 | 0.179 |
| Conv5 | 12.223 | 1.227 |
| Conv6 | 7.043 | 2.305 |
| Conv7 | 6.836 | 1.955 |
| Conv8 | 6.346 | 4.010 |
| Conv9 | 13.505 | 11.813 |
| **Conv2–9 cycle-weighted total** | **8.8486** | **3.6654** |

동시 활성화 관계를 깨트릴 때 원래 배치의 개선율이 **5.1832 percentage points** 낮아짐. 이 변화는 특히 Conv3–5에서 큼. Conv9는 평균 희소도/부하 차이만으로도 효과가 크게 유지되는 **반례**이므로 정직하게 포함.

**제한:** 셔플은 실제 FPGA에 입력한 데이터가 아니며, FPGA 가속 실측이 아니라 **검증된 Bank 모델의 반사실적 실험**이다. 각 채널별 NNZ 분포는 정확히 같지만 윈도우별 전체 NNZ 합의 분포까지 동일한 것은 아니다. 동일 한 장의 사진에 대한 conditional Monte Carlo 20회이므로 독립 이미지 모집단의 CI로 주장 금지.

## 4. 신규 오프라인 실험 B: 동일 예산 목표함수 비교

같은 물리 입력의 **상단 64행×128열** 중 1,024윈도우/레이어를 선택하는 spatial calibration. **하단 64행×128열** 8,192윈도우/레이어는 평가 전용(학습 누출 금지). 두 목적함수 모두 동일한 4-Bank 균등 그룹 조건, 초기 identity, 동일 Greedy interbank-swap search, **레이어당 401회 비용 함수 평가**, optimizer seeds=10000,10001,10002,10003.

- **Joint optimizer:** 실제 calibration 창의 동시 활성화 구조에서 Bank-max cycle 최소화.
- **Marginal optimizer:** 채널마다 calibration 창의 순서를 독립 섞은 NNZ 표본에서 동일한 Bank-max cycle 최소화. 채널별 NNZ histogram 보존.
- 두 매핑을 **원래의 하단 절반 실제 활성화 데이터**에서 동일하게 평가.

| Optimizer seed | Joint (% reduction) | Marginal-preserving shuffled (%) | Joint 우위 (pp) |
|---:|---:|---:|---:|
| 10000 | 8.6105 | 5.1667 | +3.4438 |
| 10001 | 8.5315 | 3.9061 | +4.6253 |
| 10002 | 9.1346 | 2.7244 | +6.4103 |
| 10003 | 8.8325 | 3.4137 | +5.4188 |
| **평균** | **8.7773** | **3.8027** | **+4.9745** |

**핵심 관찰:** 같은 Greedy 알고리즘/탐색 횟수와 시드에서도, 진짜 윈도우 간 채널 동시 활성화 관계를 유지한 목적함수가 공간분리 평가에서 4개 시드 모두 더 좋은 배치를 선택했음.

**강한 제한:** 한 장의 사진에서 위/아래를 나눈 실험이므로 평가 윈도우가 calibration과 공간적으로 상관되어 있고, 네 optimizer seed는 독립 clean-image 복제가 아니다. 이 결과로 BSD68 일반화 유의성/새 FPGA 가속률을 주장하면 안 된다. Q1 rebuttal용 최종 근거는 아래 독립 데이터 프로토콜이 성공한 후에만 획득.

## 5. 논문에 넣을 범위가 명확한 핵심 식

입력 window `v`, 채널 `c`별 비영 3×3 tap 수 `n_c(v)`, 정적 균등 channel-bank assignment `g`, Bank `b`에 대하여

`B_b(v;g) = Σ_{c:g(c)=b} n_c(v)`.

코어 `P=16` lane, 4개 Bank, 입력 W=4 값/cycle의 Conv2–9에서는

`C(v;g) = max(ceil(K/4)+1, ceil(Cout/16)*max(1,max_b B_b(v;g)), Cout)`.

Calibration의 경험 평균 `mean_v C(v;g)`을 최소화하고 다음 레이어의 가중치/전 레이어의 출력 필터, bias 및 per-output quantization parameter를 동시에 재배열하여 정수 출력 보존. 이 RTL 기반 cost model이나 인접층 channel permutation 보상은 **선행 사실/기존 구현**이며 새로운 공식 또는 새로운 permutation theorem이라고 주장하지 않음.

## 6. 적대적 리뷰어 반박의 현실적 형태

| Reviewer 공격 | 반박 방향 | 실제 추가 검증 |
|---|---|---|
| Channel permutation already exists (NeurIPS 2021) | 인정. novelty는 permutation 자체가 아니라 **window-correlated activation issue-cycle objective & limits** | density-sort, Greedy, marginalized shuffle equal budgets |
| Greedy balancing is obvious | 인정. 똑같은 Greedy로 목적함수 **joint vs marginal**만 통제해 4시드 차이를 보이는 것이 현재 가장 강한 ablation | BSD68 independent clean images |
| One image overfitting | 이번 05의 결과는 hypothesis screening만으로 제한 | calibration Set12 01–03, evaluation BSD68 68 clean images |
| 7.6% is small | unchanged RTL/weights/function, core-limited opportunity fraction and feed-floor proof, Conv2–9 8.85% | floor-bound characterization + E2E if claimed |
| Physical cost predictor is tautological | 38-cycle same-input match를 physical consistency evidence로만 제시 | new-image paired physical-vs-cost plots |
| Static layout cannot adapt to input drift | failure cases report. Cost-optimal static tradeoff vs dynamic scheduler | sigma 15/25/50 and negative-case panels |

## 7. 완전 독립 이미지 논문용 Gate (코드 업로드됨, 본 문서 작성 시 아직 실행 결과 없음)

**실제 GPU PC에서 실행해야 하는 남은 결정적 분석:** Set12 01/02/03, sigma25, noise seeds0/1에서 동일 예산의 Joint/Marginal 그룹 학습 → BSD68 68장, sigma15/25/50, noise seeds0/1/2에 대해 그룹 **한 번도 재선택하지 않고** 평가.

탐색 알고리즘 자체가 아닌 목적함수만 비교. Bootstrap은 **서로 다른 원본 clean image 68개 단위**로 짝맞춰 수행, noise/seed 반복을 독립 데이터로 카운트하면 안 됨.

Windows smoke (2 BSD68 images, sigma25, noise seed0; **최종 논문 결과 아님**):

    cd /d C:\fpga\FPGA
    git pull origin main
    python scripts\q1_novelty_bsd68_holdout.py --max-images 2 --sigma 25 --noise-seeds 0 --out build\q1_novelty_bsd68_smoke

Windows full (실물 FPGA JTAG 필요 없음, PyTorch/NumPy 필요):

    python scripts\q1_novelty_bsd68_holdout.py --out build\q1_novelty_bsd68_full

저장:
- `C:\fpga\FPGA\build\q1_novelty_bsd68_full\summary.json`
- `C:\fpga\FPGA\build\q1_novelty_bsd68_full\per_condition.csv`
- `C:\fpga\FPGA\build\q1_novelty_bsd68_full\groups.json`

**Go/No-Go:** independent image-based CI에서 Joint의 개선이 명확하면 co-activation-sensitive mapping을 주 신규성 후보로 승격. 평균 차이가 0에 가깝거나 부호 역전 시 새 목적함수 우월성 주장을 즉시 철회하고 현재 W4 실측을 실용 시스템 기여로만 제시.

## 8. Related Work (이미 공개된 것을 인정)

- Pool & Yu, *Channel Permutations for N:M Sparsity*, NeurIPS 2021: https://proceedings.neurips.cc/paper_files/paper/2021/hash/6e8404c3b93a9527c8db241a1846599a-Abstract.html
- SparTen, MICRO 2019: https://doi.org/10.1145/3352460.3358291
- FPGA multi-bank hash selection, Micromachines 2025: https://doi.org/10.3390/mi16010022
- Balanced Intra/Inter PE, IEEE TVLSI 2025: https://doi.org/10.1109/TVLSI.2024.3515217
- SpALEn, ACM JETC 2026: https://doi.org/10.1145/3802578
- SparHiXcel-v2, arXiv July 2026: https://arxiv.org/abs/2607.19248
- BRIM, arXiv July 2026: https://arxiv.org/abs/2607.19431

**중요:** 이 리스트는 이 논문들의 관련 개념을 대조하기 위한 기준. 이 분야 모든 선행특허/논문을 전수한 것은 아님.

## 9. 현재 Reviewer verdict

- **IF 2–3 목표:** 실제 W4 실측 7.605% + exact quantization preservation + 독립 이미지 coactivation objective 우위가 재현되면 실험적 시스템 논문으로 투고 시도 충분히 현실적.
- **Q1 목표:** 같은 근거에 더해 다른 CNN/병목 조건, negative ablation, 공정한 비교와 선행연구 차이를 강하게 제시해야 경쟁력이 생김.
- **현재:** 이 실험은 최초의 channel permutation을 증명하지 않으며, 단일 입력에서 관찰한 coactivation sensitivity라는 구체적 재현 가설을 부각시킨 상태.

## 10. 재현 코드

- `scripts/q1_coactivation_novelty_gate.py`: 실제 trial_01.zip + 보존된 Frozen/Multi permutation map으로 A/B 재현. **FPGA 프로그래밍 없음**.
- `scripts/q1_novelty_bsd68_holdout.py`: 독립 clean image 검증 (GPU PC에서 실행 필요). **FPGA 프로그래밍 없음**.
