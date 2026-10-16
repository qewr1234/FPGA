# FPGA CNN 이미지 잡음 제거기

잡음 섞인 흑백 사진을 넣으면 FPGA가 깨끗한 사진을 돌려줍니다. CIFAR 분류에 썼던 **같은 비트스트림**
(K=1152, COUT=128, P=16, T=4, 런타임 형상)을 그대로 쓰고, 망만 분류용에서 잡음 제거용으로 바꿨습니다.

## 설정

표준 설정인 DnCNN(Zhang et al., 2017)과 같습니다.

| 항목 | 내용 |
|---|---|
| 학습 사진 | Train400 (BSD 180×180 흑백 400장) 중 380장, 20장은 검증용. 40×40 또는 50×50 패치, 4가지 크기 × 8가지 뒤집기/회전 |
| 테스트 사진 | Set12 (12장), BSD68 (68장) |
| 잡음 | 가우시안 백색 잡음 σ=25 (0~255 기준) |
| 학습 종료 | 검증 PSNR이 6 epoch 동안 안 오르면 학습률 반감, 15 epoch 동안 안 오르면 종료. 검증 최고 모델 사용 |

하드웨어 때문에 바꾼 것이 두 가지 있습니다. **비교 대상도 모두 이 조건에서 다시 측정했습니다.**

1. **잡음 사진을 [0,1]로 자르고 7비트로 양자화합니다.** 코어 입력 포트가 7비트 부호 없는 값이기 때문입니다.
2. **마지막 층이 깨끗한 사진을 직접 출력합니다.** DnCNN은 잡음을 예측해서 빼지만, 코어는 모든 출력에 ReLU를 걸기 때문에 음수가 있는 잡음은 낼 수 없습니다. 잡음 사진을 마지막 층에 한 채널 더 넣습니다(skip).

## 결과 (평균 PSNR, 높을수록 좋음)

정수 = 보드와 같은 정수 연산을 PC에서 수행한 값(보드에서 실행한 일곱 모델은 Set12 05.png 한 장을 끝까지 실행해 전 층 비트 일치 확인). 사이클은 보정 사이클 모델이며, "실측"은 보드에서 잰 모델(`board_runs/`). `python denoise/results_table.py`가 export 폴더에서 이 표를 다시 만든다.

| 모델 | 사이클/픽셀 | 곱셈기 활용률 | 파라미터 | Set12 float / 정수 | BSD68 float / 정수 | BM3D(클리핑)보다 높은 사진 |
|---|---|---|---|---|---|---|
| 잡음 사진 | — | — | — | 20.33 | 20.48 | — |
| 가우시안 필터 | — | — | — | 26.56 | 26.13 | — |
| BM3D, 클리핑 7비트 입력 (논문 조건) | — | — | — | 29.95 | 28.37 | — |
| BM3D, 클리핑 없는 float 잡음 | — | — | — | 29.98 | 28.62 | — |
| DnCNN-S 공개 가중치, 같은 클리핑 입력 (float) | 9.3k (모델) | — | 556k | 30.35 | 28.89 | — |
| A `dn_d7_c32_es` (7층 × 32채널) | 1,775 (실측) | 41% | 47k | 29.87 / 29.83 | 28.83 / 28.80 | 6/12, 60/68 |
| B `dn_d10_c64_us_es` (2×2 분할, 10층 × 64) | 1,323 (실측) | 88% | 300k | 30.14 / 30.10 | 29.01 / 29.00 | 10/12, 68/68 |
| **B + QAT** `dn_d10_c64_us_es_qat` | 1,323 (실측) | 88% | 300k | 30.13 / **30.12** | 29.01 / **29.02** | 10/12, 68/68 |
| B-32 `dn_d10_c32_us_es` (10층 × 32, ReLU; 조기 종료, 갱신 4,000) | 669 | 45% | 76k | 29.18 / 29.11 | 28.28 / 28.33 | 0/12, 30/68 |
| B-32 + QAT `dn_d10_c32_us_es_qat` | 669 | 45% | 76k | 29.43 / 29.41 | 28.52 / 28.56 | 1/12, 49/68 |
| B-32 + maxout `dn_d10_c32_us_mo_es` (조기 종료, 갱신 17,760) | 675 (실측) | 87% | 152k | 29.97 / 29.75 | 28.92 / 28.68 | 5/12, 63/68 |
| B-32 + maxout + QAT `…_mo_es_qat` (조기 종료판) | 675 (실측) | 87% | 152k | 29.98 / 29.95 | 28.93 / 28.91 | 8/12, 68/68 |
| B-32 `dn_d10_c32_us_fx` (ReLU, 120 epoch 고정, 시드 1) | 669 | 45% | 76k | 29.55 / 29.51 | 28.55 / 28.53 | 2/12, 49/68 |
| B-32 + QAT `dn_d10_c32_us_fx_qat` | 669 (실측) | 45% | 76k | 29.58 / 29.62 | 28.66 / 28.68 | 5/12, 57/68 |
| B-32 + maxout `dn_d10_c32_us_mo_fx` (120 epoch 고정, 시드 1) | 675 | 87% | 152k | 30.02 / 29.86 | 28.94 / 28.80 | 6/12, 66/68 |
| **B-32 + maxout + QAT** `dn_d10_c32_us_mo_fx_qat` (속도) | 675 (실측) | 87% | 152k | 30.00 / **30.00** | 28.95 / **28.94** | 9/12, 68/68 |

- **화질 모델 B+QAT:** 클리핑 BM3D보다 Set12 +0.17, BSD68 +0.66 dB. 클리핑 없는 BM3D보다도 +0.14 / +0.40 dB(10/12, 68/68). A보다 1.34배 적은 사이클로 +0.29 / +0.22 dB(12/12, 68/68).
- **속도 모델 B-32+maxout+QAT (`dn_d10_c32_us_mo_fx_qat`):** A보다 **2.63배** 적은 사이클로 A보다 +0.17 / +0.14 dB(12/12, 64/68). Set12는 BM3D 수준(클리핑 기준 +0.04 dB, 9/12; 클리핑 없는 BM3D보다 +0.01), BSD68은 클리핑 BM3D보다 +0.57, 클리핑 없는 BM3D보다 +0.32 dB(67/68). 조기 종료판(29.95 / 28.91)과의 차이 +0.04 / +0.03 dB는 해석하지 않는다. 같은 예산 비교에 들어간 모델이라 이것을 속도 모델로 쓴다.
- **maxout의 효과 (같은 예산 재실험, 진행 중):** 조기 종료판끼리(`mo_es_qat` 대 `es_qat`)의 +0.54 / +0.35 dB는 학습 예산이 다른 비교였다(체크포인트까지의 갱신 ReLU 0.4만, maxout 1.8만). 같은 120 epoch(갱신 19,200회)과 QAT 15 epoch으로 다시 학습하니 정수 Set12 / BSD68이 ReLU 29.62 / 28.68(`dn_d10_c32_us_fx_qat`), maxout 30.00 / 28.94(`dn_d10_c32_us_mo_fx_qat`)로 +0.37 / +0.26 dB(80/80장), 정수 검증으로 +0.30 dB(28.520 대 28.221)였다. 그러나 같은 갱신 수가 같은 최적화는 아니었다. 시드 1의 ReLU 망은 epoch 26에 무너졌고(검증 27.93 → 24.27 dB), plateau 규칙이 회복 중에 학습률을 네 번 반으로 줄였다(epoch 33·40·47·54; 10⁻³에서의 갱신 5,120 대 maxout 9,280). 무너지기 전(epoch 25)에는 두 망의 검증 최고가 27.934 대 27.947로 같았다. 120 epoch 끝에 ReLU는 아직 오르고 있었고(마지막 20 epoch +0.05 dB, 학습률 6.3×10⁻⁵) maxout은 평탄했다(1.6×10⁻⁵). 차이의 일부는 이 시드의 학습률 경로 탓일 수 있어서, 시드 2·3을 같은 플래그로 돌려 판단한다(아래 '실행 순서'). 판단 규칙(시드 2·3 결과를 보기 전에 정함): 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 모두 높을 때만 '높다'고 쓰고, 평균과 범위를 함께 적는다. 평균 결합 대조군은 maxout과 초기 가중치·데이터가 같고(같은 시드) 합치는 방식만 다르다. 정수 경로에서 반올림을 한 번 더 하므로 float 차이도 함께 본다. 시드 1의 평균 결합(`dn_d10_c32_us_avg_fx`)은 검증 최고 28.549 dB(epoch 117), float Set12 30.05 dB(epoch 117)로 maxout(28.528, 30.02)과 같거나 약간 높았다. 마지막 20 epoch의 검증 평균은 +0.018 dB(20 epoch 모두 평균 결합이 높음), 120 epoch 중 87 epoch에서 평균 결합이 높았다. 붕괴는 없었고 학습률 경로는 maxout과 거의 같았다(첫 감소 epoch 59). 이 시드에서는 max 비선형이 아니라 늘어난 공짜 출력 채널이 차이를 만든다. QAT 뒤 정수 값은 아직 없다. 사이클은 첫 층(K=36 < 출력 64)이 출력 64개를 내보내는 시간 때문에 1% 많다(675.25 대 668.5).
- **QAT의 효과:** 정수 손실(Set12 / BSD68)이 같은 예산판 maxout 0.16 / 0.14 → 0.01 / 0.01, ReLU 0.05 / 0.02 → 정수가 float보다 0.04 / 0.02 높음, B 0.04 → 0.01 dB(조기 종료판 maxout 0.22 → 0.02). 모두 0.04 dB 이내.
- **BM3D 조건:** 클리핑 7비트 입력은 BM3D에 BSD68 0.26 dB 손해를 준다(`bm3d_protocol.py`; 포화 픽셀이 많은 영상에 집중). σ를 학습 영상 40장에서 다시 골라도(σ=23) −0.06 / +0.09 dB로 0.1 dB 이내.
- **같은 입력의 DnCNN-S:** `dncnn_s_protocol.py`. 공개 가중치(float, 556k, 클리핑 없이 학습)가 30.35 / 28.89(클리핑 없는 입력 30.44 / 29.24로 문헌 재현). 화질 모델은 Set12 0.2 dB 낮고 BSD68 0.1 dB 높지만, 후자는 학습 분포 차이라 이득으로 세지 않는다.
- 시드가 하나라(학습 1, QAT 3) 0.1 dB 미만 차이는 해석하지 않는다.

### 왜 이런 설계인가: 사이클 모델

창 하나의 비용은 `max(K, ⌈COUT/P⌉ × ⌈K/T⌉)` 사이클(P=16, T=4)이다. 입력 포트가 사이클당 값 하나를 받으므로 K보다 빨라질 수 없고, **COUT ≤ P·T = 64이면 출력 채널은 비용이 없다.** 보드 실측은 여기에 창당 +1, 그리고 창당 최소 COUT 사이클(코어가 출력을 사이클당 하나씩 내보냄)이 더해진다. 보정 전 모델의 오차는 0.4–1.6%(B-32 ReLU 0.38%, B 0.70%, B-32 maxout 1.37%, A 1.63%), 보정 모델은 네 망(A, B, B-32 maxout, B-32 ReLU)에서 0.003% 이내(`train_denoise.board_cycles_per_pixel_measured`).

- A의 중간 층(K=288, COUT=32)은 계산에 144 사이클이면 되는데 입력에 288이 걸린다. 곱셈기 활용률 41%.
- **B (space-to-depth):** 창 수가 1/4이 되므로 같은 사이클 예산에 채널 64, 10층 망이 들어간다. K=576, COUT=64에서 입력과 계산이 정확히 균형(망 전체 활용률 88%). 파라미터 6.4배, 곱셈 1.6배인데 사이클은 25% 적다. B 대 A의 화질 차이는 리샘플링만의 효과가 아니라 더 큰 망의 효과다.
- **B-32 + maxout:** 채널 32(K=288)로 돌아오면 출력 64까지가 다시 공짜. 은닉층이 채널마다 후보 두 개를 내고(출력 64) PC가 재양자화할 때 큰 쪽만 넘긴다(`max(ReLU(a), ReLU(b))` = maxout). 다음 층 K는 그대로. 보드에서 이 층은 **289 사이클/창**으로 A의 출력 32 층과 같았다. 첫 층(K=36)만 출력 64개를 내보내는 64 사이클이라 픽셀당 669 → 675. 활용률 45% → 87%.
- **병목의 출처:** 입력 포트가 사이클당 값 하나인 것은 AXI-Stream 래퍼의 설계다(`rtl/window_mac_axis.sv`: 전송 단위(beat)당 값 4개를 1개/사이클로 풀어 넣음). 포트를 4-wide로 넓히면 K=288·COUT=64 층은 연산 바운드(288 대 ReLU 144)가 되어 maxout은 공짜가 아니다. 공짜 출력 채널의 한계는 대략 곱셈기 수 / 입력 폭(1값 64, 2값 32, 4값 16)이다. 창을 PC가 만드는 것도 같은 역할이다. 칩 안 라인 버퍼 구조에서는 dense 모델로 은닉층이 COUT=32에서 145, 64에서 289 사이클/창이 되고, 망 전체로 A 833, B 1,209, B-32 ReLU 319, B-32 maxout 615 사이클/px가 되어 maxout은 ReLU의 약 2배 비용이 되고 B는 A보다 느려진다(예측). 규칙은 이 입력 구조에 조건부다. 2값/사이클이면 A 907, B 1,247, B-32 ReLU 339, B-32 maxout 635 사이클/px로, 이미 maxout은 1.87배, B는 A의 1.37배다(4값/사이클은 라인 버퍼와 같은 값).
- **host의 몫:** im2col, 재양자화, maxout의 max를 합쳐 장당 0.07–0.13 s(4코어, numpy, 대부분 재양자화)로 50 MHz 코어 시간의 5–9%다(`python scripts/time_host.py`). 표의 벽시계는 JTAG 전송과 보드 쪽 검증 시간이다.
- **보드 실행 모드:** 모든 실행이 sparse 모드(`mode_seq=1`, 0인 활성값의 곱셈을 건너뜀)였다. 입력 항 K는 그대로라 입력에 묶인 층의 사이클은 dense와 같다. 같은 비트스트림의 CIFAR-10 실행에서 K=576, COUT=128 층은 sparse로 591.5 사이클/창이었다(dense COUT>64는 보드 미측정).

### 보드 실측 (Set12 05.png, 256×256)

모든 층의 출력이 PC 정수 모델과 비트 단위로 일치(0 mismatches)했고, PSNR은 `int_eval.json`과 같다. 기록: `board_runs/*.json`(`scripts/run_denoise.py`의 report.json 원본).

| 모델 | 클럭 | 층 | K | COUT | 사이클/창 | 총 사이클 | 코어 시간 | 벽시계(JTAG 포함) | PSNR |
|---|---|---|---|---|---|---|---|---|---|
| B + QAT | 50 MHz | conv1 / conv2–9 / conv10 | 36 / 576 / 612 | 64 / 64 / 4 | 64 / 577 / 613 | 86,721,997 (1,323/px) | 1.73 s | 600 s | 20.23 → 30.06 |
| B-32 + maxout + QAT `…_mo_fx_qat` | 50 MHz | conv1 / conv2–9 / conv10 | 36 / 288 / 324 | 64 / 64 / 4 | 64 / 289 / 325 | 44,254,293 (675/px) | 0.89 s | 408 s | 20.23 → 29.94 |
| B-32 ReLU + QAT `…_fx_qat` | 50 MHz | conv1 / conv2–9 / conv10 | 36 / 288 / 324 | 32 / 32 / 4 | 37 / 289 / 325 | 43,811,412 (668.5/px) | 0.88 s | 292 s | 20.23 → 29.54 |
| B-32 + maxout + QAT `…_mo_es_qat` (조기 종료판) | 50 MHz | 같음 | | | 64 / 289 / 325 | 44,254,269 (675/px) | 0.89 s | 371 s | 20.23 → 29.87 |
| 같은 모델 | 100 MHz | 같음 | | | 같음 | 44,254,269 | 0.44 s | 399 s | 20.23 → 29.87 |
| A `dn_d7_c32_es` | 50 MHz | conv1 / conv2–6 / conv7 | 9 / 288 / 297 | 32 / 32 / 1 | 32 / 289 / 298 | 116,326,743 (1,775/px) | 2.33 s | 701 s | 20.23 → 29.83 |

사이클 수는 클럭과 무관하다(100 MHz 실행이 50 MHz와 동일). 같은 구조라도 가중치가 다르면 sparse 모드의 층별 사이클이 몇 사이클 달라진다(조기 종료판과 같은 예산판 maxout+QAT: 44,254,269 대 44,254,293). 은닉층(conv2–9) 입력의 0이 아닌 값 비율은 ReLU+QAT 0.37–0.55, maxout+QAT 0.64–0.84(보드 기록 `nonzero_fraction`)라서, maxout은 사이클만 같고 곱셈은 더 한다(전력은 재지 않음). 절대 처리량은 50 MHz·곱셈기 64개로 약 5.7 GOPS.

비교 그림: `figures/05_dn_d10_c64_us_es_qat_board.pdf` (B+QAT, 30.06 dB). `make_figure.py --model dn_d10_c64_us_es_qat --board build/denoise_run_b_qat`로 만든다. 사이클 대 PSNR 산점도(논문 그림 2): `python denoise/plot_psnr_cycles.py` → `figures/psnr_vs_cycles.pdf`.

## 실행 순서

```
python denoise/get_data.py                           # 사진 받기 (16 MB)
python denoise/baselines.py                          # 비교 대상 측정 (BM3D 포함 약 10분)
python denoise/train_denoise.py --unshuffle --depth 10 --channels 32 --maxout --patch 50 --patches 20480 \
       --epochs 300 --schedule plateau --name dn_d10_c32_us_mo_es        # 이전 속도 모델(조기 종료판; 지금 속도 모델은 아래 'maxout 대조 실험'의 dn_d10_c32_us_mo_fx), 약 3시간
python denoise/qat_denoise.py --ckpt denoise/dn_d10_c32_us_mo_es.pt --epochs 15   # 양자화 인지 미세조정 (약 1시간)
python denoise/quantize_denoise.py --ckpt denoise/dn_d10_c32_us_mo_es_qat.pt       # 보드용 파일 + 정수 PSNR
python scripts/run_denoise.py --emulate --model dn_d10_c32_us_mo_es_qat            # 보드 없이 전체 흐름 확인
python scripts/run_denoise.py --model dn_d10_c32_us_mo_es_qat --xsdb <xsdb.bat 경로> --images 05.png   # 보드
python denoise/results_table.py                      # 결과표
python denoise/bm3d_protocol.py all                  # 클리핑 조건이 BM3D에 주는 영향 (약 35분)
python denoise/dncnn_s_protocol.py <cszn/DnCNN model.pth>   # 공개 DnCNN-S를 같은 입력으로 (약 5분)
```

화질 모델은 `--channels 64`에 `--maxout` 없이 같은 순서입니다.

**maxout 대조 실험 (같은 학습 예산).** 기존 B-32 ReLU는 epoch 26에 검증 PSNR이 무너진 뒤 회복하지 못해 epoch 40에 조기 종료됐고(최고 epoch 25, 갱신 4,000회), maxout은 갱신 17,760회에서 최고였다. 그래서 세 망을 조기 종료 없이 같은 120 epoch(갱신 19,200회)으로 다시 학습한다. `--avgout`은 같은 64 출력을 재양자화 뒤에 평균으로 합친다(파라미터·코어 비용이 maxout과 같고 max 비선형만 없다; 범위는 합치기 전 값으로 보정).

```
set F=--unshuffle --depth 10 --channels 32 --patch 50 --patches 20480 --epochs 120 --schedule plateau --stop-patience 1000 --min-lr 0 --threads 5
python denoise/train_denoise.py %F% --name dn_d10_c32_us_fx
python denoise/train_denoise.py %F% --avgout --name dn_d10_c32_us_avg_fx
python denoise/train_denoise.py %F% --maxout --name dn_d10_c32_us_mo_fx
REM 각 X에 대해: python denoise/quantize_denoise.py --ckpt denoise/X.pt
REM              python denoise/qat_denoise.py --ckpt denoise/X.pt --epochs 15
REM              python denoise/quantize_denoise.py --ckpt denoise/X_qat.pt
REM 시드 2·3: 같은 F에 --seed N, 이름 끝에 _sN (예: dn_d10_c32_us_mo_fx_s2). 창 하나에서 네 단계를 &&로 잇는다:
REM python denoise/train_denoise.py %F% --maxout --seed 2 --name dn_d10_c32_us_mo_fx_s2 && python denoise/quantize_denoise.py --ckpt denoise/dn_d10_c32_us_mo_fx_s2.pt && python denoise/qat_denoise.py --ckpt denoise/dn_d10_c32_us_mo_fx_s2.pt --epochs 15 --threads 5 && python denoise/quantize_denoise.py --ckpt denoise/dn_d10_c32_us_mo_fx_s2_qat.pt
``` 7층 망은 `--depth 7 --channels 32 --patches 32768`(unshuffle 없음).

스크립트가 하는 일:
- `train_denoise.py`: 망은 노드 그래프입니다(`node`, `unet_spec`). 각 노드는 코어 한 번(창 kh×kw, stride, dilation, COUT)이고, 입력 맵 여러 개를 이어 붙일 수 있으며, 후처리(maxout, pixel shuffle)는 PC 몫입니다. 사이클 모델과 보정 모델을 출력합니다.
- `qat_denoise.py`: 보드의 정수 연산(INT8 가중치, 7비트 활성값, 바이어스 단위, skip 스케일 접기, 재양자화 뒤 maxout, 8비트 출력)을 float 안에서 straight-through로 재현한 `FoldedQ`를 미세조정합니다. 활성값 스케일은 학습 변수(LSQ). 검증은 양자화를 켠 채로 하므로 남는 모델이 보드 모델입니다.
- `quantize_denoise.py`: 그래프를 정수로 바꾸고, 합성곱 형태와 보드가 스트리밍하는 im2col 형태가 모든 노드에서 같은지 확인한 뒤 export합니다. QAT 체크포인트는 범위 탐색 없이 학습된 스케일을 씁니다.
- `scripts/run_denoise.py`: 그래프를 순서대로 보드에서 실행합니다. 층마다 im2col을 만들어 CIFAR 때와 같은 보드 경로로 실행하고, 보드 쪽에서 정답과 비트 단위로 비교하며, 최종 PSNR이 `int_eval.json`과 다르면 멈춥니다. 512×512는 DMA 한도 때문에 창을 나눠 실행합니다.

## 실험 기록

### 잔차(잡음) 학습 — 정수에서 손해

마지막 층을 부호만 다른 두 채널 (w, b), (−w, −b)로 만들어 PC에서 ReLU(z) − ReLU(−z) = z로 잡음을 복원하는 방식(`--residual`, `dn_d7_c32_res`). float에서는 기존과 같았지만(−0.02 dB) 정수에서 0.3 dB를 잃었습니다(29.34 대 29.55). 원인은 확인하지 않았습니다.

### maxout — 7층 32채널에서는 효과가 작음

7층 × 32채널(K=288, 출력 64)에서 15 epoch 같은 조건 비교: 검증 PSNR이 12/15 epoch에서 maxout이 높았지만 마지막 5 epoch 평균 차이는 +0.02 dB(최고 epoch 기준 +0.12, 스크린 변동 약 0.4 dB 안; `screening/screen_A_*_train.json`). 10층 32채널(B-32)에서는 같은 예산(시드 1)의 QAT 대 QAT로 +0.37 / +0.26 dB(조기 종료판끼리의 +0.54는 예산이 다른 비교); 시드 2·3으로 확정합니다. 64채널에서는 출력 128이 K를 넘겨 공짜가 아닙니다.

### 층별 활성값 범위 선택

맵마다 퍼센타일을 검증 영상 40장에서 따로 고릅니다(후보 11개, 공통값 뒤 맵별 보정). 예전 B 체크포인트에서 정수 손실 0.15 → 0.02 dB. 채널 간 범위 맞추기(cross-layer equalization)는 skip 가중치를 거칠게 만들어 더 나빴습니다.

### 2단계 U-Net — 같은 사이클에서 뒤짐

리샘플링이 공짜라는 성질로 깊이를 1/16 해상도에 두는 U-Net(`--arch unet`, 1,294 사이클/px, 669k 파라미터)을 30 epoch 비교: 검증 27.89 dB 대 B 28.14 dB(`screening/scr_unet_g2_train.json`). 경사 갱신이 100 대 160으로 적긴 했지만 이득의 조짐이 없어 보류했습니다.

### 문헌 조사

`research/novelty_search_KO.md`: 8개 관점의 조사와 9개 아이디어의 반박 검증 기록.
