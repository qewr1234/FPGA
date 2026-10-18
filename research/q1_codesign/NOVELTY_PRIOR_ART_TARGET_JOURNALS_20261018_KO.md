# 2026-10-18 최신 선행연구 조사 · Q1/IF 2~3 현실적인 신규성 및 투고 전략

> 근거: 2026-10-18까지 공개된 arXiv 2024~2026, 주요 IEEE/ACM/Elsevier/MDPI 논문의 공개 초록 및 접근 가능한 본문. 유료 본문 전체, 모든 arXiv 논문을 전수 조사한 것은 아니다. IF/Q는 2025 JCR(2026 발표) 기준으로 기재하며 최종 제출 전 공식 JCR 재확인.

## 0. 현재 물리 증거

- 한 가지 INT8 QAT 10-layer CNN, Set12 05.png sigma25 seed0, 4bank W4 50MHz XC7Z020 실물 W4 core. Original 13,289,030 cycles, Frozen 12,355,814 (3회차 12 DMA stall 추가), Multi 12,278,419. 전체 Conv1~10 실제 7.60485%, Conv2~9 실제 8.84855% 절감.
- 동일 RTL/bitstream SHA: 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6.
- 9회 모델 실행의 Conv별 exact oracle 및 세 모델 결과 이미지 동일. 활성값 채널 재배열 동치. 동일 입력 window max-bank 비용 모델 예측 절감 1,010,573 cycles, 실물 절감 1,010,611 cycles, 절감량 차이 38 cycles.
- BSD68 68×3 sigma×3 seed=612 조건의 Conv2~9 모델 예측 Frozen 10.1247%, Multi 10.70885%; physical 05 한 장과 직접 같은 모집단으로 비교하지 말 것. Equal-budget B400/B800/B2000에서 Multi가 Greedy에 대해 일관되게 우월하지 않다.

## 1. 핵심 선행연구와 실제 위험

| 논문 | 날짜·근거 | 기존에 해낸 것 | 본 연구의 차이와 남은 취약점 |
|---|---|---|---|
| Pool & Yu, Channel Permutations for N:M Sparsity | NeurIPS 2021, https://proceedings.neurips.cc/paper_files/paper/2021/hash/6e8404c3b93a9527c8db241a1846599a-Abstract.html | 인접층 보정형 채널 순열; inference-time extra reorder 제거, permutation search | **채널 순열 자체의 신규성 없음**. 우리의 목적 함수는 N:M weight quality가 아니라 *활성화 window의 synchronous bank core cycles*. 반박에는 실제 측정과 floor/issue 분석 필요 |
| SparTen | MICRO 2019, https://doi.org/10.1145/3352460.3358291 | offline Greedy Balancing, filter density 기반 sparse hardware scheduling | Greedy load balance 자체의 신규성 없음; activation co-occurrence 및 model-graph function preservation/unchanged bitstream을 비교해야 함 |
| Xu et al., Sparse Convolution FPGA Accelerator Based on Multi-Bank Hash Selection | Micromachines 2025, https://doi.org/10.3390/mi16010022 | FPGA multi-bank task scheduling, sparse weight channel imbalance, filter/kernel rearrangement | 가장 가까운 FPGA 선행연구; **first bank-aware reordering 주장 금지**. static activation window maximum NNZ와 unchanged RTL, no runtime shuffler를 정확히 분리 |
| An Efficient Sparse CNN Inference Accelerator with Balanced Intra- and Inter-PE Workload | IEEE TVLSI 2025, https://doi.org/10.1109/TVLSI.2024.3515217 | valid-weight encoding, randomized load rearrangement, recurrent weight stationary, FPGA | weight-imbalance vs activation bank-imbalance, unchanged original weight values and PSNR comparison |
| Pan et al., pattern-compressed sparse CNN FPGA | Neurocomputing 2025, https://doi.org/10.1016/j.neucom.2024.128700 | weight workload fusion, activation hash conflict reduction and hierarchical mapping, ZCU102 | activation conflict ≠ synchronous max-bank nonzero workload. Comparative claims require hardware/data normalization |
| Longchar & Kapoor, SpALEn | ACM JETC 2026, https://doi.org/10.1145/3802578 | PE zero-skipping, runtime workload reassignment and independent filter assignment; evaluation largely Cadence synthesis/simulator | static offline placement avoids runtime scheduler/control but no universal superiority. No true apples-to-apples absolute 12x comparison |
| Zarei & Vakili, SparHiXcel-v2 | arXiv Jul 2026, https://arxiv.org/abs/2607.19248 | column-wise kernel compression, filter execution reordering, structured pruning/revival, Kintex FPGA | weight column movement + hardware architecture changes vs activation-preserving channel-to-bank reparameterization on existing RTL |
| Manjunath et al., BRIM | arXiv Jul 2026, https://arxiv.org/abs/2607.19431 | offline profiled activation statistics, cyclic-balanced weight pruning + dynamic bit-serial hardware slot donation | offline activation statistics are NOT novel; specific integer activation-bank sync max-cost with zero pruning/retraining and unchanged hardware is target |
| Wang et al., SparDR | JSA 2026 online; Vol 181 December, https://doi.org/10.1016/j.sysarc.2026.104029 | compile-time feature map dataflow reconstruction, pre-addressed weight representation, TVM multi-platform sparse inference | compile-time data rearrangement generic claim preempted. Our specific FPGA bank-cost minmax offline channel assignment must be scoped narrowly |
| Lu et al., A low-cost hardware-algorithm co-optimized architecture | Microelectronics Journal Apr 2026, https://doi.org/10.1016/j.mejo.2026.107065 | round-robin PE balance + sensitivity-aware structured pruning, measured FPGA | no pruning, bitexact output, no new control hardware vs RRAS/APLS, but practical benefit needs independent proof |

## 2. 최종적으로 추천하는 좁고 실증 가능한 신규성

**현실적인 novelty claim:** *Calibration-guided, function-preserving static channel-to-bank mapping for activation-sparse quantized CNNs, directly minimizing window-wise synchronized bank issue cycles on an unchanged FPGA bitstream.*

신규성이 **아닌 것**: channel permutation, adjacent-layer permutation compensation, greedy/multi-start, offline mapping 일반, FPGA 희소 부하 균형 일반, zero runtime shuffle 일반, min–max scheduling 자체.

구별할 **복합 문제 정의**:

- 입력 window v, 채널 c의 3×3 nonzero 활성값 n_c(v); 균등 bank g(c)=pi(c) mod B;
- Bank workload M_b(v)=sum_{c:g(c)=b} n_c(v), synchronized issue latency = ceil(Cout/P) max(1,max_b M_b(v));
- input/output floor F(v)=max(ceil(K/W)+1,Cout);
- 모델 C(v,pi)=max(F(v), ceil(Cout/P)*max(1,max_b M_b(v)));
- calibration set S에서 pi를 고정 선택, μ = mean_{v in S} C(v,pi) 최소화; 배포 시 새로운 인덱싱/셔플 커널 없이 export 가중치와 requant 인접 채널 축에 순열 흡수.
- *완화된 가상 하한*: L(v)=max(F(v), ceil(Cout/P)*max(1,ceil(sum_c n_c(v)/B))) — 각 window별 탭을 독립 이동하는 비현실적 오라클이므로 실제 달성 가능 최적값으로 표현 금지.
- *음성/실패 조건*: 이미 feed/output floor 지배라면 절감 불가; dense (모든 채널 입력 비영, 균등 bank)라면 재배열 이득 없음; 모델/잡음 변동에서 특정 층 악화 가능 (기존 Conv7 sigma50).

### 실질적 강점 3개

1. **Co-activation-sensitive objective**: 채널별 평균 zero율만 정렬하지 않고 같은 window에서 동시 nonzero인 채널의 bank assignment를 최적화. Per-image/per-window max-bank cost vs marginal density-sort의 차이를 보여야 함.
2. **Valid INT8 transformation with formal assumptions**: Conv output filters/bias/per-output requant를 동일 permutation; 다음 Conv input-channel weights를 역전환 대응. ReLU 및 독립 per-channel quantizer 사슬에 대한 귀납적 동치 정리. 임의 branching/depthwise/Maxout까지 증명됐다고 과장하지 않음.
3. **Effectiveness limits + physical matched cost**: floor-bound/issue-bound phase diagram, 레이어·sigma별 하한 접근률, 실제 50 MHz physical core savings and same-input prediction gap (38 cycles), no FPGA re-synthesis. 이 수식의 RTL 유도 사실은 본문에 명시하고 처음 발견된 공식을 주장하지 않음.

### 작은 추가 실험/수정으로 논문 강화

- 기존 greedy와 multistart를 억지로 신알고리즘으로 포장하지 않는다. 단일 *robust* 보정 항 J=(1-λ) mean_s C_s + λ max_s C_s를 추가 검토 가능하나 반드시 fair-budget, unseen sigma evidence를 먼저 확인. 개선이 없으면 버려도 무방.
- Pairwise co-activation correlation / bank occupancy 그림 1개, static channel density-sort vs joint window-aware objective, data distribution drift 대응 실패 케이스.
- 매개변수 W/B/P 변경 시 최대 개선이 가능한 영역의 조건부 수학적 정의; W1에서는 **해당 측정 구조에서 floor 지배일 때만** 이득이 사라진다고 제한.

## 3. 적대적 리뷰어 반론 / 현실적 반박

| 반론 | 과장 없는 대응 | 필수 표/실험 |
|---|---|---|
| 'NeurIPS 2021이 permutation 했다' | 인정. 우리는 구조화 sparsity accuracy를 올리는 permutation 논문이 아니라, post-QAT activation bank **measured latency objective**와 제한 조건을 다룬다 | 관련연구 direct claim matrix, no-retraining exact quantization lemma |
| 'Greedy load balance=일반 balanced partition' | 인정. optimizer 자체가 아니라 per-window correlated work + output/feed floor + exact deployment으로 기여를 정의 | density-sort/mean-NNZ/20+ random vs floor-aware window optimizer, equal-budget |
| '왜 겨우 7.6%?' | 총 10층에 최적화 불가 Conv1·10, input/output floor 존재. 이득 가능 상한/상한 대비 회수율 제시 | bottleneck ablation, floor-bound ratio, oracle relaxed lower bound |
| 'RTL 식과 RTL 측정이 맞는 건 당연' | cycle model first-order performance predictor이지 이론의 최초 발견 주장 아님. 동일 입력 채널 변환의 예측 차이 38 cycles를 실물 검증으로 사용 | per-layer physical vs predicted delta/ residuals, co-activity figure |
| '하드웨어 바꾸지 않았다=기여 없다' | 그게 trade-off다: post-training INT8 software layout + independent bit exact + 0 added runtime kernel, FPGA same bitstream. 단 end-to-end latency 개선 및 config bytes도 구분 | unchanged RTL/bitstream hash, area unchanged, host/PS/DMA cycles vs core |
| '한 장으로 일반화 못 한다' | 인정. blind independent images/model/sigma, CI across independent images, negative cases 공개 | BSD68 or test image holdout, second CNN, additional physical subsets |
| 'Multi-start이 항상 낫지 않다' | 인정. 핵심 방법은 max-bank cost aware mapping. multi-start는 선택적 optimizer로만 부록 | strict equal cost evaluations, grouped seeds with Greedy wins |

## 4. 현실적 최소 투고 Gate

**IF 2~3 저널을 목표로 (권장 최소)**:
- 2개의 CNN 설정 (가능하면 32ch+64ch), 서로 다른 여러 미사용 영상에서 실제 W4 core speedup 및 exact results;
- calibration vs evaluation 엄격히 분리, sigma15/25/50 및 여러 seed의 **독립 이미지별** confidence interval (n=이미지 수; 반복 실험은 n을 늘리지 않는다);
- Original, random 20~30 fixed seeds, density-sort, fair-budget greedy, proposed bank-cost aware 매핑 (최소 4종);
- W1/dense negative controls or cost-model ablation: '적용 불가능/이득 없음' 조건을 포함;
- area, Fmax, config bytes, extra runtime shuffler 0, Conv1–10 PL core and Conv2–9 PL core; system-level latency는 명확히 분리해서 최소 측정 혹은 claim 제한.

**JCR Q1 도전을 위해 보강**:
- 다른 데이터셋의 완전한 FPGA subset과 2~3 model architectures, bank widths/W/P 변경 반응, theoretical relaxed oracle bound와 failure-region 일반화.
- 여러 input conditions의 physical vs predicted paired validation, uncertainty, non-improvement 사례 포함.
- prior 2025 multi-bank, SparHiXcel and SpALEn 대비 같은 원리 수준의 강한 matched controls, 가능하면 end-to-end PS/DDR/PL response.

## 5. 저널 후보: 2025 JIF (2026 발표)

| 후보 | JIF, JCR quartile | 적합성 / 부담 | 출처 |
|---|---|---|---|
| Journal of Systems Architecture | ~5.3 / Q1 (공개 2차 JCR 기록) | 야심 찬 상향지원. 적용 조건 일반화와 full-system 근거 상당히 요구 | https://researchcloud.net/journal/1383-7621 |
| Microprocessors and Microsystems | 2.6 / Q2 (JCR 2차 기록) | **가장 현실적인 1순위**. Embedded HW/SW mapping + physical FPGA 실측과 잘 맞음 | https://www.sciencedirect.com/journal/microprocessors-and-microsystems ; https://journalsimpactfactors.com/journal.php?id=6275 |
| Electronics | 2.9 / Q2 (JCR, 공식 출판사) | **실용적 IF 2~3 후보**. JCR Q2임. Scopus CiteScore Q1과 혼동 금지, APC 고려 | https://www.mdpi.com/news/17132 |
| Microelectronics Journal | 2.2 / Q3 근거 보조 검색 | FPGA hardware-specific 실험 및 co-design 친화적. Q1 요구 시 부적합 | https://www.bioxbio.com/journal/MICROELECTRON-J |
| ACM TRETS | ~2.8 / Q2 (외부 지표; 공식 JCR 재확인) | FPGA 분야 직접 전문성이 높아 선행연구 대비 엄격한 강점 설명 필요 | https://doi.org/10.1145/3687480 |

Q1 분류와 IF2~3은 다른 조건이다. 모든 IF와 quartile은 제출일의 공식 Clarivate JCR 카테고리별 결과로 재확인하고 제출 규정/예산까지 확인해야 한다.

## 6. 추천 제목/기여문장

**논문 제목 후보**: *Function-Preserving Activation-Aware Channel-to-Bank Mapping for Sparse Quantized CNNs on FPGA*

**기여 1**: Define a calibration-guided channel-to-bank assignment objective that targets input-dependent synchronized bank issue cycles rather than channel-wise sparsity alone.

**기여 2**: Integrate this objective with function-preserving quantized CNN graph reparameterization without additional runtime shuffle, retraining, or RTL changes (on supported ReLU/per-channel quantized chains).

**기여 3**: Quantify floor-bound versus bank-bound opportunity and validate predicted and physical W4 FPGA core-cycle reductions using multiple unseen workloads, including failure cases.

Abstract에서 7.60%는 현재 *Set12 05.png 한 장*의 실제 Conv1–10 PL core cycles이고 10.70885%는 BSD68 *모델 추정 Conv2–9*라는 원칙을 유지한다.

## 7. 추가 검토가 필요한 부분

- 정확하게 동일한 static channel-to-bank, activation co-occurrence objective를 다룬 arXiv/논문 존재 여부는 비포괄적 검색 결과로 **미확정**. SOTA 연도/버전 및 유료 본문 검토 후 novelty claim 재검증 필요.
- 현재 'unchanged FPGA hardware'라는 표현은 bitstream 그대로라는 뜻이지, arbitrary FPGA vendor/board에 범용 호환이라는 뜻이 아니다.
- IF2~3 Journal에서도 new idea vs implementation trade-off reviewer 지적은 유효. 모든 실험이 성공한다고 accept가 보장되지 않는다.

