# 적대적 리뷰어 심사 (2026-10-18): 문제점 · 수정 · Go/No-Go

**상태: 논문 기여 아직 미입증.** 본 문서는 실제 GitHub 구현과 보드 기록을 바탕으로 심사 위협을 노출한 내부 연구 메모. 선행연구 차이점은 공개 논문/초록에 근거하며 모든 유료 본문을 조사했다고 주장하지 않는다.

## A. 강한 선행연구와 유사성

1. **HW-Flow-Fusion (Electronics, 2022):** 레이어 간 스케줄링, 타일, 데이터 재사용과 분석 모델. https://doi.org/10.3390/electronics11182933
2. **Falcon (IEEE TVLSI, online 2024 / issue 2025):** 이미지 복원용 CNN의 혼합 재사용/재계산, feature-map buffer, throughput/EMA/energy Pareto. **ASIC 구현/레이아웃**이지 FPGA 실측으로 인용하면 안 된다. https://doi.org/10.1109/TVLSI.2024.3488042
3. **USEFUSE (Journal of Systems Architecture, 2025):** 멀티 레이어 Fusion, 동일한 Tile movement, 중복 계산 절감. https://doi.org/10.1016/j.sysarc.2025.103459
4. **NAF (DATE 2023):** 네트워크·비트폭·가속기·매핑의 공동 탐색. 따라서 'PSNR-레이턴시 공동최적화' 자체가 새로울 수 없음. https://doi.org/10.23919/DATE56975.2023.10137094
5. **NeurIPS 2021: Channel Permutations for N:M Sparsity:** 다음 레이어 가중치와 이전 레이어 채널 순서를 함께 재배열해 추론 중 추가 reorder 없이 출력 보존 가능. 즉 **채널 순열 자체**는 선행기술. https://proceedings.neurips.cc/paper/2021/hash/6e8404c3b93a9527c8db241a1846599a-Abstract.html
6. **Micromachines 2025 Multi-Bank Hash Selection:** sparse CNN 부하 균형·멀티 뱅크·계산 스케줄. https://doi.org/10.3390/mi16010022
7. **IEEE TVLSI 2025 Balanced Intra/Inter PE Sparse CNN:** 희소 부하 불균형 해결 및 FPGA 검증. https://doi.org/10.1109/TVLSI.2024.3515217
8. **ReTiDe (arXiv 2025):** FPGA INT8/QAT 이미지 노이즈 제거, 화질/전력 효율. https://arxiv.org/abs/2510.03812

## B. 치명적 반박과 해결 수준

| 리뷰어 반박 | 현재 자료로 확인한 사실 | 이번 해결책 | 남은 증거 |
|---|---|---|---|
| '레이어 Fusion은 이미 있다' | HW-Flow-Fusion/Falcon/USEFUSE에서 수행 | **Fusion을 주 신규성에서 제외**, 보조 아키텍처 후보로 격하 | 새로운 방법이 선행기법보다 좋아야 함 |
| '80% 트래픽 감소는 가공된 숫자' | `q1_fusion_cost.py`의 가정값, 측정치 아님 | 논문의 성능 주장·초록에서 제거 | RTL+PS DDR 카운터 실측 필요 |
| 'DMA가 이미 안 멈춘다' | QAT ReLU Conv2 1,504,752, Conv3 1,435,005 cycles. IN_STALL 0+0. 총 네트워크 13,289,042 cycles. **2층이 22.12%**, 계산 상한 Amdahl | **핵심 실험을 Activation-bank 일정 변경**으로 전환 | 실제 보드에서 유지되는 compute-cycle 감소 |
| 'Joint optimization/NAS는 이미 있다' | NAF 및 다른 NAS 선행연구 존재 | 일반 NAS 주장 금지. **활성값 희소 뱅크별 max-load 때문에 발생하는 W1↔W4 regime-crossing**의 직접적인 데이터/계측 모델만 가설로 검토 | NAF형 정합 baseline 대비 성능 향상 |
| '순열도 이미 있다' | NeurIPS 2021, 2025 sparse balance 논문 | **새 기여 주장하지 않고** 기존 코어 전용 bank-permutation 의 강한 baseline 역할로 먼저 사용 | 랜덤·채널 density-sort와 차이가 없으면 순열 방법 기각 |
| '화질이 바뀌었나?' | 기존 데이터는 정수 ReLU QAT | Conv2→3 weight/requant bit-exact selftest, 순열 전체 모델을 re-export 후 01/05 전체 영상 픽셀 0 mismatch 검증 구현 | 지금은 실행 전. RTL 재양자화 검증 별개 |
| 'Set12 05 하나만 보고 모델 골랐다' | 기존 W4 보드 결과는 Set12 05, σ25, 50MHz | Set12 01로 임시 캘리브레이션 → 05로 임시 평가 분리; 코드에서 선택 이미지와 평가 이미지 교집합 금지 | **논문 제출용으로는 Train400 calibration, 독립 테스트 BSD68/CBSD68, σ15/25/50 및 여러 시드 필요** |
| '공정한 비교가 없다' | 현재 W1/W4 네 모델 실측은 비교일 뿐 방법론 비교 아님 | FLOPs/PSNR 기준, identity/density-sorted/20x random 순열, W1 대조군, bank-awareness ablation을 사전 등록 | 실측 검증 + 통계, 해당 분야의 강한 SOTA 공정 매핑 |
| '코어 사이클과 진짜 제품 속도를 혼동' | 기존 JTAG wall clock 수백초, core-only 계산 0.266s @50MHz | **core cycles, FPGA+DMA transfer, PS preprocess, host/JTAG wall clock을 분리** | 새 PS/Linux driver와 동등한 통합 시스템 계측 |
| 'BRAM +22는 단순 용량 계산' | BRAM RAMB36 68+RAMB18 6, 100MHz WNS 0.130ns는 기존 ZedBoard 실적 | FPGA 논문 주요 기여에서 아직 제외 | Smart ZYNQ SL 전용 PS/DDR/MIO, RTL synthesis/route timing |

## C. 핵심 구조 가설 — 새로운 발견이라고 주장 금지

기존 sparse W=4 banked MAC의 창당 사이클 계수:

`C_window ≈ max(ceil(K/4)+1, ceil(COUT/16) * max(1, max_b NNZ(activation_taps_in_bank_b)), COUT)`

이 실측-기반 모델은 `denoise/predict_w4.py`, `denoise/w4_measured.json`에 이미 존재하며 **기존 프로젝트의 결과**임.

3×3, 입력 채널 C=32에서는 tap 순서 `(ky,kx,cin)`와 `T=4`이므로 bank index = `channel_index mod 4`. 그러므로 활성값 채널을 순열하면 매 bank의 `nonzero` 분포가 달라져 issue cycle이 바뀔 수 있다. 가중치 입력축과 앞 레이어의 출력축, bias 및 `requant`를 일관되게 순열하면 CNN의 출력은 동일해야 한다.

**검증 질문:** 해당 순열을 calibration 데이터에서만 선택했을 때, 평가 영상의 최악 뱅크 부하 `max_b NNZ`가 줄어 실제 W=4 core cycle이 줄어드는가? W=1 (K=288 load 289)에서는 그 차이가 사라지는가? Dense 모드에서는 차이가 사라지는가?

## D. GPU PC 즉시 실행

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_GPU_Q1_REVIEW.cmd
```

환경은 기존 PyTorch + CUDA + NumPy. Vivado 필요 없음. 실행 실패 시 에러를 보낼 것.

결과 1: `build/q1_reviewer_bank/report.json` (실제 정수 가중치의 원래 추론 활성값으로 추정한 **core cycles만**; 랜덤·density 정렬 대조군 포함)

결과 2: `build/q1_reviewer_export/dn_d10_c32_us_fx_qat/bitexact_report.json` (재배열된 가중치 Export vs 원본 모델의 **전체 영상 출력 픽셀 차이**)

검증 통과 전에는 이 방법이 실제로 작동한다고 말하지 않는다. `w4` 논리식에서의 예상 감소는 보드 타이밍이 아니며, exporter는 CPU bitexact만 확인한다.

## E. 엄격한 Go/No-Go

- **G0:** 올바른 정수 Export. 모든 완전한 영상에서 0 pixel mismatch. 실패 시 중단.
- **G1:** 적어도 conv2..9의 다수 레이어에서 평가 데이터의 예측 core cycles 감소. Density-sorted와 random median을 못 이기면 그리디 permutation 기각.
- **G2:** 완전히 분리된 학습/테스트 데이터에서 반복 측정. 01/05 Set12는 사전 탐색용이지 학술 독립 검증 아님.
- **G3:** 동일 FPGA 비트스트림, 동일 fclk, 동일 이미지에서 원본과 순열 Export의 실제 코어 사이클을 비교. 모델이 새 장치에 전달되는 방식과 채널 순서 바꿈이 정확히 반영되는지 확인.
- **G4:** W=1 및 Dense 대조군을 포함해 변화를 설명할 것. 간단한 density-sort/랜덤보다 효과가 없으면 논문 novelty 포기.
- **G5:** FPGA 실측 후 동등한 PSNR 제약하에 실제 CNN 후보 간 선택 문제와 통계/ablation 확장. NAF, hardware-aware mapper와 동급 공정 비교 없으면 공동최적화의 독립적 기여 주장 금지.

### 논문 주장 권한

- **지금 주장 가능:** 기존 ZedBoard 기반 W=4에서 CNN 비용 순위가 달라졌고, activation bank max-count 사이클 모델이 보드 측정과 일치했다. 지금 수행 중인 새로운 순열/융합 실험은 *가설*.
- **아직 주장 금지:** FPGA 전체 시스템 80% 트래픽 절감, FPGA 속도 향상, 전력 절약, 실시간 처리, 최초 기술, Q1 수락 가능성.

### 가능한 논문 프레이밍 (Gate 충족 시만)

*Quality-Preserving Activation-Bank Scheduling and Bankwidth Regime Analysis for Quantized CNN Denoising on Low-Cost FPGAs*

단, 실제 최근 논문이 그래프 동치 채널 순열+뱅크 희소 부하 최적화를 이미 다루므로 이 제목 자체로 신규성 보장 없음. 학술 기여는 기존 일반적 접근이 놓치는 **검증 가능한 추가 성질/알고리즘/실측 우위**가 나왔을 때만 정의한다.
