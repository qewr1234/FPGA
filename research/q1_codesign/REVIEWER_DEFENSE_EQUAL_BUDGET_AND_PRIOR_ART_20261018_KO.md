# Q1 리뷰어 방어 — 선행연구 비교와 필수 실험 게이트 (2026-10-18)

이 문서는 기존 GPU 결과(업로드된 EVIDENCE_REPORT_KO.md 및 paired_tests.json)와 공개 논문을 근거로 작성한 보강 계획이다. **신규 FPGA 결과나 알고리즘 신규성을 새로 입증한 문서가 아니다.**

## 1. 어떤 기여를 주장할지

가제: **Hardware-Cycle-Aware, Function-Preserving Channel Layout Optimization for Banked Sparse INT8 CNN Inference**

가능한 포지셔닝:
- 기존 채널 순열/인접 가중치 재배열 아이디어를 인정한다.
- 특정 동기식 W=4 Sparse 코어에서 활성화의 윈도우별 nonzero count가 Bank별 최대 issue 비용을 만드는 현상에 집중한다.
- 정적 offline calibration으로 채널 그룹을 고르고 가중치와 양자화 파라미터에 흡수해 inference-time shuffle 커널을 추가하지 않는다.
- 그 결과를 실제 10-layer INT8 QAT CNN과 FPGA에서 같은 bitstream·동일 clock으로 측정한다.

**주장 금지**: 최초의 channel permutation, 최초의 sparse load balancing, multi-start 탐색 자체의 신규성, 10.709% FPGA 실측, zero system overhead, 모든 CNN 범용성.

## 2. 선행연구 충돌 비교

| 연구 | 해당 연구가 이미 달성한 것 | 이번 연구와 구별해야 할 점 | 리뷰어가 지적할 약점 |
|---|---|---|---|
| Pool & Yu, **Channel Permutations for N:M Sparsity**, NeurIPS 2021 | 주변 레이어를 조정하는 채널 순열, 고품질 순열 탐색, runtime 효율 유지 | N:M 가중치 sparse 정확도 최적화 vs 고정 INT8 CNN의 **활성화 희소성 기반 4-bank 실제 실행비용** | channel permutation / local minima escape 자체는 신규 아님 |
| Gondimalla et al., **SparTen**, MICRO 2019 | Sparse CNN 내 Greedy Balancing, 필터 밀도 기반 GB-S/GB-H | 필터 작업 할당 vs 원본 기능을 보존한 input-feature 채널의 static bank placement | Greedy balancing 자체는 알려진 연구 |
| Soltaniyeh et al., **SPOTS**, ACM TACO 2022 | Sparse convolution systolic GEMM, load imbalance 분석, weight block reshuffle와 output reorder 부담 논의 | 우리는 인접 레이어의 가중치를 같은 순열로 치환하여 따로 output shuffle 커널을 만들지 않음 | 인접층 치환 원리는 NeurIPS 선행연구와 겹침 |
| Xu et al., **Sparse Convolution FPGA Accelerator Based on Multi-Bank Hash Selection**, Micromachines 2025 | weight zero skipping, 공유 feature-map cache, hash 주소를 이용한 bank access conflict 감소 | *Cache bank collision* 문제가 아닌 *activation work imbalance* 문제 | bank/sparse라는 말만으로 새롭다고 주장할 수 없음 |
| Longchar & Kapoor, **SpALEn**, ACM JETC 2026 | 동적 PE 작업 재할당 및 runtime zero skipping | 소프트웨어 측의 offline layout 최적화로 기존 RTL 유지 | 동적 재할당 방식과의 차별성·제약·적용 가능 조건을 밝혀야 함 |
| Parashar et al., **SCNN**, ISCA 2017 | weight/activation sparse dataflow acceleration | 이미 완성된 W4 sparse accelerator에서 보드 부하 균형 목적의 모델 배치 | sparse CNN 자체를 발명한 것으로 표현 불가 |

출처:
1. https://proceedings.neurips.cc/paper_files/paper/2021/hash/6e8404c3b93a9527c8db241a1846599a-Abstract.html
2. https://doi.org/10.1145/3352460.3358291
3. https://doi.org/10.1145/3532863
4. https://doi.org/10.3390/mi16010022
5. https://doi.org/10.1145/3802578
6. https://doi.org/10.1145/3079856.3080254

**금지 비교:** 각 논문의 GOPS/FPGA resource/speedup과 본 연구의 W4 core proxy를 직접 나란히 놓고 절대 우열 주장. 데이터, 하드웨어, workload, 최적화 수준이 다르다.

## 3. 코어 비용 모델을 명확히 정의

3×3 conv의 입력 윈도우 v와 원본 채널 c, Bank 할당 g(c)∈{0,1,2,3}, 채널 c의 3×3 tap 중 nonzero 수 n_c(v)에 대해

B_b(v;g) = sum_{c:g(c)=b} n_c(v)

T_hat(v;g) = max( ceil(K/4)+1, ceil(Cout/16)*max(1,max_b B_b(v;g)), Cout )

Calibration objective: mean_{v in calibration windows} T_hat(v;g)

제약조건: 각 Bank에 동일한 수의 input channels 할당. 기존 32ch에서는 bank별 8개, 64ch에서는 bank별 16개.

이 함수는 scripts/q1_reviewer_bank.py의 실제 계산과 맞춰 작성했으며 **대상 레이어의 core-window coefficient 추정**이다. 전체 레이어 fill/drain, PS, DMA/JTAG setup, memory control stall 및 전력을 포함하지 않는다.

핵심 분석 과제: input read floor ceil(K/4)+1 또는 Cout floor가 이슈 항을 압도하는 창의 비율을 측정해, 왜 어떤 데이터에서는 순열 효과가 아예 없는지 설명한다.

## 4. 출력 보존의 증명 범위

층 l에 대해 hidden feature channel 순열 P_l을 적용할 때 앞쪽 Conv의 output filter·bias·per-output requant을 P_l로 동시 재정렬하고, 뒤쪽 Conv input-channel tap weights를 같은 P_l과 일관되게 재정렬한다.

기능 보존은 ReLU 및 per-channel quantization이 채널별로 독립적인 범위에서, hidden 레이어를 순회하는 귀납법으로 증명할 수 있다. 다만 **실험한 ReLU32의 마지막 output layer를 재배열하지 않고 skip-image branch는 원순서 그대로 유지한다**는 실제 구현을 명시해야 한다.

Maxout, arbitrary branching, grouped/depthwise conv, 새로운 skip/concat 패턴까지 자동으로 기능 보존이 증명됐다고 주장하지 않는다.

## 5. 리뷰어 방어 Gate

| Gate | 질문 | 필요한 결과 | 현재 상태 |
|---|---|---|---|
| G1 정확성 | 출력 결과를 바꾸지 않는가 | 32ch ReLU 720조건 0 pixel diff 및 수학적 변환 정리 | 전수 검증 샘플 완료, formal proof 문서화 필요 |
| G2 공정성 | Multi-start가 5배 이상 탐색한 것 아닌가 | 동일 Calibration, 동일 목적함수 **평가 횟수**, 다중 optimizer seed | 새 GPU equal-budget script 게시, 사용자가 실행해야 함 |
| G3 물리효과 | 실제 FPGA는 빨라졌는가 | Original/Frozen/Multi-start, same verified W4 bitstream, 3회, full 10 layer PL core cycle 및 stalls | 새 board triplet script 게시, 아직 미실측 |
| G4 end-to-end | 호스트 im2col/JTAG 포함 체감은 | host pre/post + transfer 시간을 PL core와 별도 측정 | 미실측 |
| G5 범용성 | 새로운 CNN에서도 맞는가 | 64ch/Maxout 가중치 export + bitexact 필요 | 현재 virtual cost study |
| G6 novelty | 기존 채널 순열과 다른가 | Hardware-specific synchronous max-bank cycle model의 직접 입증, matched-cost prior baselines | 문서화 및 추가 근거 필요 |

## 6. 기존 GPU 결과의 정직한 문장

BSD68 68 images × sigma15/25/50 × AWGN seeds0/1/2에 대해:
- Fixed Frozen: 10.125%, Multi-start: 10.709%, Greedy: 10.389%, Anneal: 10.513%, density sorting 2.703%, 전부 W4 Conv2-9 analytical core coefficient reduction.
- Multi-start − Frozen paired difference +0.584 pp, bootstrap CI [+0.516,+0.651] pp. 68 이미지 중 67 이미지 개선.
- sigma50에선 Frozen이 더 나음: 14.037% vs Multi-start 13.892%, 분포 변화에 따라 최적순열이 변함.
- Original vs Frozen와 Original vs Multi-start의 별도 720조건 전체 최종 output pixel 불일치 0.
- 64ch ReLU 최대 9.946%, Maxout 최대 4.237%은 가상 채널 배치의 모델 추정이며 실제 export 검증이 아니다.

## 7. 실행 (Windows GPU PC)

cd /d C:\fpga\FPGA

git status

git pull origin main

RUN_GPU_Q1_FAIR_BUDGET_SMOKE.cmd

RUN_GPU_Q1_FAIR_BUDGET.cmd

결과: build/q1_gpu_fair_budget/summary.json, method_summary.csv, fair_paired.csv, search_effort.csv.
비교 연구에서 같은 *cost-function evaluation count*를 맞춰도 실제 CPU 탐색 시간은 다를 수 있으므로 각 방법의 search_seconds도 함께 보고.

## 8. FPGA PC

cd /d C:\fpga\FPGA

git status

git pull origin main

RUN_FPGA_Q1_TRIPLET_PREFLIGHT.cmd

사전 점검 단계는 보드에 **접근하지 않는다**. 실제 보드 빌드가 Smart ZYNQ SL의 PS DDR/MIO에 안전한지 매뉴얼/설계와 대조한 뒤에만 별도의 RUN_FPGA_Q1_TRIPLET.cmd 실행.

명령:
RUN_FPGA_Q1_TRIPLET.cmd "C:\PATH\TO\xsdb.bat" "C:\PATH\TO\VERIFIED_SMART_ZYNQ_SL_W4_BUILD" trial_01

경로는 placeholder로 실제 경로를 입력. 기존 ZedBoard 펌웨어를 무작정 실행하지 않는다.
3회 반복 후 build/q1_bank_fpga_triplet/trial_01/triplet_summary.md 및 triplet_summary.json 생성.

## 9. Q1 현실적 판정

Novelty는 여전히 잠정적이다. 동일 최적화 예산을 통제했는데 성능 차이가 작아지는 경우, 'Multi-start superiority'를 핵심 기여로 삼지 않는다. 실제 hardware cycle model과 물리 측정의 일치도, 기존 비트스트림 불변 및 조건부 성능 이득의 구조적 설명을 우선한다.

마감에 필요한 것은 주장되지 않은 신규성보다 **관찰한 성능의 원인과 적용 범위를 정확히 검증한 자료**다.
