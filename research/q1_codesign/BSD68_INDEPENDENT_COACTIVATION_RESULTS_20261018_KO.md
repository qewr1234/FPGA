# 독립 BSD68 검증 — Joint co-activation vs Marginal-preserving channel bank mapping

**날짜:** 2026-10-18. **근거 파일:** 사용자가 제공한 `q1_novelty_bsd68_full.zip` 내부 `summary.json`, `per_condition.csv`, `groups.json`, `progress.json`. 전체 ZIP CRC 검증 통과. 본 문서는 파일 재집계 결과이며 새 FPGA 보드 측정은 아님.

## 결과 무결성

- 원본 clean image: **68개 BSD68**. Calibration: **Set12 01~03.png** (sigma25, noise seeds 0/1).
- Evaluation: sigma 15/25/50 × noise seed 0/1/2 × optimizer seed 13/42/127/612.
- Total **68 × 3 × 3 × 4 = 2,448 rows**, `per_condition.csv`의 (image, sigma, noise_seed, optimizer_seed) 조합 중복 0; `progress.json`도 2,448행 완료.
- `groups.json`은 optimizer seed별 **Conv2~9의 8개 균형 4-bank/8-channel 배치**를 Joint와 Marginal에 각각 저장하고 있음. 그룹 정합성 및 모든 score 수치 유한성 확인.
- 알고리즘 비교: 양쪽 모두 동일 greedy bank-swap, 동일 초기 순열, 시드, 레이어당 **401 objective evaluations**, 동일 Calibration windows 2048 (스크립트 기본값). 차이는 실제 채널 동시활성화 배열을 보존 vs 채널별 window 순서를 독립 permutation하여 marginal NNZ histogram만 보존한 학습 비용 테이블.

## 결과 핵심

| 조건 | Joint core proxy 절감(%) | Marginal core proxy 절감(%) | Joint 추가 이득 (percentage points) |
|---|---:|---:|---:|
| **BSD68 전체 2,448 조건** | **10.264387** | **3.512257** | **+6.752130** |
| σ15 | 7.992026 | 2.951527 | +5.040499 |
| σ25 | 9.298326 | 4.360274 | +4.938052 |
| σ50 | 13.103178 | 3.242359 | +9.860819 |

최적화 시드별 짝맞춘 전체 결과:

| Seed | Joint (%) | Marginal (%) | Joint advantage (pp) |
|---|---:|---:|---:|
| 13 | 10.224241 | 3.467005 | +6.757236 |
| 42 | 10.457529 | 2.834621 | +7.622908 |
| 127 | 9.948605 | 4.792126 | +5.156479 |
| 612 | 10.427173 | 2.955276 | +7.471897 |

- Per-condition comparison: Joint lower cost **2,448/2,448**, ties 0, losses 0.
- Per-image aggregate: Joint better **68/68**, clean-image aggregate advantage **+5.844853 to +8.295919 pp** across images.
- User summary `image_cluster_bootstrap95_pp`: **[+6.630959,+6.882967] percentage points**, 2,000 image-level resamples. Cluster is clean image, not 2,448 artificially independent samples. However four optimizer seeds are fixed; this interval **does not quantify optimizer-seed uncertainty** or selection history.

## Reviewer 주장 범위와 주의

**가능한 claim:** A calibration-guided window-wise channel co-activation-aware bank mapping objective yields substantially lower **analytical W4 sparse Conv2–9 core cycles** than the matched greedy optimizer trained on independently permuted channel-marginal NNZ sequences, on unseen BSD68 clean images and noise configurations.

**금지 claims:** '이번 실험에서 실제 FPGA가 10.26% 빨라졌다', '모든 다른 sparse accelerator와 CNN에서 우월하다', 'N:M channel permutation을 최초 발명했다', 'Marginal 방법이 최강 density-based baseline이다', '2,448개의 독립 이미지 검증' 등. 10.26%는 비용 모델, 실제 FPGA 물리 실측은 별도 1 Set12 사진의 전체 Conv1–10 7.605% 및 대상 Conv2–9 8.849%.

**리뷰어가 제기할 수 있는 공격과 대응 계획:**

1. Marginal Null은 **각 채널의 NNZ histogram**은 정확히 보존하나 동일 window의 **전체 NNZ/공간적 상관**을 보존하지 않으므로 현실적인 기존 방법과 일대일 비교가 아니다. 이를 co-activation 기여 분석용 **controlled ablation**으로 정확히 명명.
2. Density sorting, correlation-blind greedy/grouping, 20~30 static balanced random, equal-budget conventional Greedy 등 강한 실제 baseline을 **같은 calibration/evaluation split**에서 별도로 비교할 것. 현재 coactivation vs scrambled marginal 결과만으로 SOTA를 뛰어넘는다고 주장할 수 없음.
3. 다른 CNN 구조와 물리 FPGA의 unseen image subset, W1/dense negative cases, 혹은 적어도 feed-floor/issue-bound 구조적 경계를 점검할 것.
4. 내부 패러미터 및 quantized model 자체가 BSD68을 과거 모델 선택에 활용했을 가능성을 구분. 이번 permutation 선택은 BSD68을 사용하지 않았지만 전체 개발 역사의 완전한 dataset-level blindness는 미입증.
5. 다른 무작위 optimizer seed 집합을 시험하고 seed-level scatter/variation을 병기. Image bootstrap confidence interval은 seed 불확실성까지 대표하지 않음.

## 결정

**GO (방법론의 주된 독립 데이터 근거 확보):** 모든 68 clean images에서 동일 예산 Joint objective가 marginals-only null objective보다 좋은 W4 analytical cost를 얻음. 적어도 이 특정 지원 가속기 및 QAT ReLU CNN에선 channel coactivation relation이 실질적으로 중요하다는 가설을 강하게 지지.

**NOT YET CLAIMED:** Q1 게재 확정, 최초 원리, SOTA 대비 구조적 우위, 실제 FPGA BSD68 10.26% 개선, end-to-end 지연 개선.

## 원본 파일 저장

User-uploaded ZIP: `q1_novelty_bsd68_full.zip`, 내부 `q1_novelty_bsd68_full/{summary.json,per_condition.csv,groups.json,progress.json}`. 연구 저장소에 원본 데이터를 자동 업로드하지 않음. 코드: `scripts/q1_novelty_bsd68_holdout.py`. 재현 세부정보는 `research/q1_codesign/COACTIVATION_NOVELTY_GATE_20261018_KO.md` 참조.
