# IWEICT 2026 — 제목·초록 제출용

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 별도 업로드. 웹사이트 기준 초록 10월 16일, 최종본 10월 23일(2026-10-15 확인; 저자가 받은 안내로는 초록이 10월 19일로 연장).

2026-10-16 판: 라인 버퍼 예측 문장을 정확하게 고쳤다. 두 선택의 이점이 "모두 사라진다"가 아니라, maxout은 더는 공짜가 아니고(ReLU의 약 2배 사이클) 망 B는 기준 망보다 느려진다(B-32 maxout은 라인 버퍼에서도 A보다 빠르다고 예측된다). 길이를 맞추려고 K 구절을 줄였다. 같은 예산(120 epoch + QAT 15 epoch)의 ReLU·maxout 결과는 정수 +0.37 / +0.26 dB(Set12 / BSD68, 한 시드)지만, 이 시드에서 ReLU 망이 epoch 26에 무너졌고 plateau 규칙이 회복 중에 학습률을 먼저 낮췄다(무너지기 전에는 두 망의 검증 PSNR이 같았다). 그래서 시드 2·3이 나오기 전에는 숫자를 초록에 넣지 않는다. 판단 규칙(결과를 보기 전에 정함): 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 높으면 (a), 아니면 (c). 시드 결과 전에 제출해야 하면 (c). 이전 판의 +0.54 / +0.35 dB는 ReLU 망이 갱신 0.4만에서 조기 종료된 비교라 쓰지 않는다.

2026-10-16 (이후) 판: 평균 결합 대조군이 maxout과 같아서(시드 1), maxout 문장을 "출력을 2배로 늘려 두 개씩 합치면 파라미터 2배를 사이클 1%로 얻고, 이득은 max가 아니라 공짜 용량에서 온다"로 바꿨다. 마지막 문장은 2값/사이클도 함께 적는다. 시드 2·3 결과에 따라 아래 [SEEDS] 규칙을 적용한다.

2026-10-16 (밤) 판: 외부 심사(Reject 의견)를 반영해 초록의 숫자를 절반쯤으로 줄이고(PSNR은 화질 모델의 Set12 하나만), "일곱 모델"을 "네 가지 망"으로, 마지막 문장을 측정한 병목에 따른 선택으로 한정했다.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

## Abstract (English)

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. On our integer CNN core for a Zynq XC7Z020 FPGA (64 multipliers, 7-bit inputs), we show how the measured bottleneck changes the design of a Gaussian denoiser. A cycle model that predicts the board within 0.003% shows that this build, fed host-built windows one value per cycle, is bound by its input port: a window of K values costs K cycles for up to 64 output channels, so a DnCNN-style baseline leaves most multipliers idle. Two choices that look wasteful by FLOP count therefore pay off. A 2×2 space-to-depth input fits a 6.4× larger network in 25% fewer cycles. Doubling the hidden outputs and pooling them in pairs (maxout) doubles the parameters for 1% more cycles; at the same training budget it denoises better than the ReLU network of the same width, and in one seed averaging the pairs did as well, pointing to the free capacity rather than the max [SEEDS] [AVG]. With quantization-aware training that reproduces the board's arithmetic, the quality model reaches 30.12 dB on Set12 (σ = 25), above BM3D on the same input, and the speed model matches BM3D in 2.63× fewer cycles than the baseline; four networks were verified bit for bit on the board. The same model predicts that with two input values per cycle pooling stops being free, and with four or with line buffers the 6.4× larger network becomes slower than the baseline: the network to choose follows the measured bottleneck.

**[SEEDS] [AVG]** 시드 2·3이 나오면 초록의 maxout 문장 뒷부분("; at the same training budget it denoises better … rather than the max [SEEDS] [AVG].")을 아래 셋 중 하나로 바꾼다. 평균 결합 구절은 평균 결합의 QAT 정수 값과 시드 2가 나오고, 어느 테스트셋에서도 maxout보다 0.1 dB 이상 낮지 않을 때만 "averaging the pairs instead does as well: the gain is the free capacity, not the max"로 쓴다. 아니면 "and in one seed averaging the pairs did as well"로 남기거나 지운다.

- (a) 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 높으면: "; at the same training budget it scores +X / +Y dB above the ReLU network of the same width (mean of three seeds), and averaging the pairs instead does as well: the gain is the free capacity, not the max." 평균 결합이 maxout보다 어느 한 테스트셋에서라도 0.1 dB 이상 낮으면 뒷부분을 ", and +Z / +W dB above a control that averages the pairs"로 바꾼다.
- (b) 방향은 같지만 숫자를 줄이고 싶으면: 지금 문장에서 [SEEDS] [AVG]를 지우고 "(three seeds)"를 넣는다(평균 결합 구절은 위 조건대로).
- (c) 시드가 엇갈리거나 결과 전에 제출하면: 뒷부분을 지우고 "…doubles the parameters for 1% more cycles."로 끝낸다.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 보통 곱셈 수를 최소화하도록 설계되지만, 소형 가속기에서는 실행 시간이 다른 것으로 정해질 수 있다. 직접 설계한 Zynq XC7Z020 FPGA용 정수 CNN 코어(곱셈기 64개, 7비트 입력)에서, 측정된 병목이 가우시안 잡음 제거망의 설계를 어떻게 바꾸는지 보인다. 보드를 0.003% 안에서 맞히는 사이클 모델은, PC가 만든 창을 사이클당 값 하나씩 받는 이 구현이 입력 포트에 묶여 있음을 보인다. 값 K개의 창은 K 사이클이 들고 출력 채널은 64개까지 비용이 없어서, DnCNN 형태의 기준 망은 곱셈기 대부분을 놀린다. 그래서 연산량 기준으로는 낭비로 보이는 두 선택이 이득이 된다. 2×2 space-to-depth 입력은 6.4배 큰 망을 25% 적은 사이클에 넣는다. 은닉층 출력을 2배로 늘려 두 개씩 합치면(maxout) 파라미터가 2배가 되는 대신 사이클은 1%만 늘고, 같은 학습 예산에서 같은 폭의 ReLU 망보다 잡음을 더 잘 제거한다. 시드 1에서는 두 값을 평균으로 합쳐도 같아서, 차이를 만든 것은 max가 아니라 공짜 용량으로 보인다 **[SEEDS] [AVG]**. 보드 연산을 재현한 양자화 인지 학습으로 화질 모델은 Set12에서 30.12 dB(σ = 25)로 같은 입력의 BM3D보다 높고, 속도 모델은 기준 망보다 2.63배 적은 사이클로 BM3D 수준이다. 네 가지 망을 보드에서 비트 단위로 검증했다. 같은 모델은 입력이 사이클당 2값이면 합치기가 공짜가 아니게 되고, 4값이거나 라인 버퍼를 두면 6.4배 큰 망이 기준 망보다 느려진다고 예측한다. 고를 망은 측정한 병목에 따라 달라진다.

**[SEEDS] [AVG]** 영문과 같은 규칙: (a) "같은 학습 예산에서 같은 폭의 ReLU 망보다 +X / +Y dB 높고(시드 셋의 평균), 평균으로 합쳐도 같아서 이득은 max가 아니라 공짜 용량에서 온다" (b) 지금 문장에 "(시드 셋)"을 넣는다 (c) "…사이클은 1%만 는다."로 끝낸다.

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 30.00 / 28.94 (정수 PSNR; 속도 모델은 `dn_d10_c32_us_mo_fx_qat`), QAT 뒤 손실 0.04 dB 이내 | `denoise/export/<model>/int_eval.json`; 표는 `python denoise/results_table.py` |
| maxout 대 ReLU, 대 평균 결합 (재실험) | `dn_d10_c32_us{_mo,,_avg}_fx[_sN]_qat`의 int_eval (같은 120 epoch + QAT 15 epoch, 시드 1·2·3) |
| B 대 A +0.29 / +0.22 (정수, QAT) | `dn_d10_c64_us_es_qat` 대 `dn_d7_c32_es` |
| BM3D 29.95 / 28.37, 클리핑 없이 29.98 / 28.62 | `denoise/baselines.json`, `denoise/bm3d_protocol.json` |
| DnCNN-S 같은 입력 30.35 / 28.89 (본문 표 I) | `denoise/dncnn_s_protocol.json` |
| 289 사이클/창, 675·668.5·1,323·1,775 사이클/px, 0 mismatches, 네 가지 망(학습 모델 일곱 개) | `denoise/board_runs/*_05.json` (B-32 ReLU는 `dn_d10_c32_us_fx_qat_05.json`) |
| 1.7% (보정 전) / 0.003% (보정 후), 41% 활용률 | `train_denoise.board_cycles_per_pixel` 대 `_measured` 대 `board_runs/` |
| 6.4배 파라미터 (300k / 47k), 1.6배 곱셈, 25% 적은 사이클 (1,323 / 1,775) | `denoise/README_KO.md` 표 |
| 같은 파라미터의 ReLU 망(45채널) 934 사이클/px(+38%), sparse 모드의 0이 아닌 곱셈 3.0배 | `train_denoise.board_cycles_per_pixel_measured`(45채널 형상), `board_runs/dn_d10_c32_us_{fx,mo_fx}_qat_05.json`의 `nonzero_fraction` |
| 2값/사이클 예측 (A 907, B 1,247, maxout 1.87배) | 같은 모델, 입력 항 ⌈K/2⌉ (`PAPER_KO.md` 표 III) |
| 라인 버퍼 예측 (maxout 289 대 ReLU 145 사이클/창, A 833 대 B 1,209 사이클/px) | dense 사이클 모델, 새 값은 창당 C_in개 (README "병목의 출처") |
