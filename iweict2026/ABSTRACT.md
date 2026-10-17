# IWEICT 2026 — 제목·초록 제출용

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 별도 업로드. 웹사이트 기준 초록 10월 16일, 최종본 10월 23일(2026-10-15 확인; 저자가 받은 안내로는 초록이 10월 19일로 연장).

2026-10-16 판: 라인 버퍼 예측 문장을 정확하게 고쳤다. 두 선택의 이점이 "모두 사라진다"가 아니라, maxout은 더는 공짜가 아니고(ReLU의 약 2배 사이클) 망 B는 기준 망보다 느려진다(B-32 maxout은 라인 버퍼에서도 A보다 빠르다고 예측된다). 길이를 맞추려고 K 구절을 줄였다. 같은 예산(120 epoch + QAT 15 epoch)의 ReLU·maxout 결과는 정수 +0.37 / +0.26 dB(Set12 / BSD68, 한 시드)지만, 이 시드에서 ReLU 망이 epoch 26에 무너졌고 plateau 규칙이 회복 중에 학습률을 먼저 낮췄다(무너지기 전에는 두 망의 검증 PSNR이 같았다). 그래서 시드 2·3이 나오기 전에는 숫자를 초록에 넣지 않는다. 판단 규칙(결과를 보기 전에 정함): 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 높으면 (a), 아니면 (c). 시드 결과 전에 제출해야 하면 (c). 이전 판의 +0.54 / +0.35 dB는 ReLU 망이 갱신 0.4만에서 조기 종료된 비교라 쓰지 않는다.

2026-10-16 (이후) 판: 평균 결합 대조군이 maxout과 같아서(시드 1), maxout 문장을 "출력을 2배로 늘려 두 개씩 합치면 파라미터 2배를 사이클 1%로 얻고, 이득은 max가 아니라 공짜 용량에서 온다"로 바꿨다. 마지막 문장은 2값/사이클도 함께 적는다. 시드 2·3 결과에 따라 아래 [SEEDS] 규칙을 적용한다.

2026-10-16 (밤) 판: 외부 심사(Reject 의견)를 반영해 초록의 숫자를 절반쯤으로 줄이고(PSNR은 화질 모델의 Set12 하나만), "일곱 모델"을 "네 가지 망"으로, 마지막 문장을 측정한 병목에 따른 선택으로 한정했다.

2026-10-17 판: 시드 2·3이 나왔다. 정수(QAT) Set12 / BSD68: ReLU 29.62 / 28.68, 29.94 / 28.91, 29.89 / 28.88, maxout 30.00 / 28.94, 29.91 / 28.89, 29.99 / 28.95. 시드 2에서 ReLU가 높아(−0.03 / −0.02 dB) (a)의 조건(모든 maxout 시드 > 모든 ReLU 시드)이 깨졌으므로 **(c)를 적용했다.** maxout 문장은 "…doubles the parameters for 1% more cycles."로 끝나고, 평균 결합 구절도 함께 빠진다. 앞 문장의 "therefore pay off"는 maxout의 화질 이득을 더는 말하지 않으므로 "are therefore cheap"으로 바꿨다(space-to-depth의 화질은 다음 문장의 화질 모델이 말한다). 시드 평균 차이는 +0.15 / +0.10 dB이지만 규칙대로 초록에는 넣지 않고, 본문에 시드별 값과 함께 적었다.

2026-10-17 (늦은 밤) 판: 4값 변형을 보드에서 돌렸다. 네 망 모두 불일치 0이고 총 사이클은 비트스트림 전에 커밋한 예측(7e81f6b)보다 0.0009–0.0044% 많았으며, B ÷ A 1.19, 합치기 2.48배가 측정으로 나왔다(`denoise/w4_measured.json`). 그래서 괄호를 "(on a four-value variant the board matched it within 0.005%)"로 바꿨다(10단어, 248단어). 0.0044%라서 0.004%가 아니라 0.005%로 적었다. 2값과 라인 버퍼는 예측 그대로다.

2026-10-17 (밤) 판: 사이클당 4값을 받는 코어 변형을 만들어 실제 잡음 제거 창(네 망의 모든 층, 층마다 512개)으로 RTL 시뮬레이션했다. 출력은 정수 모델과 같고 사이클은 예측에 쓴 창당 계수와 층마다 164 사이클 안에서 맞았다(`denoise/w4_rtl_sim.json`). 그래서 마지막 문장의 "with four" 뒤에 "(where RTL simulation of a four-value variant agrees on real windows)"를 넣었다(+11단어, 249단어). 보드 측정은 아직이며, 나오면 이 괄호를 측정으로 바꾼다. 2값과 라인 버퍼는 예측 그대로다. 숫자의 출처 표의 2값·라인 버퍼 줄은 창을 센 값(`denoise/wider_ports.py`)으로 바꿨다.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

## Abstract (English)

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. On our integer CNN core for a Zynq XC7Z020 FPGA (64 multipliers, 7-bit inputs), we show how the measured bottleneck changes the design of a Gaussian denoiser. A cycle model, corrected on earlier board runs and within 0.003% of the board on four networks, shows that this build, fed host-built windows one value per cycle, is bound by its input port: a window of K values costs K cycles for up to 64 output channels, so a DnCNN-style baseline leaves most multipliers idle. Two choices that look wasteful by FLOP count are therefore cheap. A 2×2 space-to-depth input fits a 6.4× larger network in 25% fewer cycles. Doubling the hidden outputs and pooling them in pairs (maxout) doubles the parameters for 1% more cycles. With quantization-aware training that reproduces the board's arithmetic, the quality model reaches 30.12 dB on Set12 (σ = 25), above BM3D on the same input, and the speed model matches BM3D in 2.63× fewer cycles than the baseline; four networks were verified bit for bit on the board, a full image each. The cycle model predicts that with two input values per cycle pooling stops being free, and with four (on a four-value variant the board matched it within 0.005%) or with line buffers the 6.4× larger network becomes slower than the baseline: the network to choose follows the measured bottleneck.

**[SEEDS] [AVG]** (2026-10-17: (c) 적용함) 시드 2·3이 나오면 초록의 maxout 문장 뒷부분("; at the same training budget it denoises better … rather than the max [SEEDS] [AVG].")을 아래 셋 중 하나로 바꾼다. 평균 결합 구절은 평균 결합의 QAT 정수 값과 시드 2가 나오고, 어느 테스트셋에서도 maxout보다 0.1 dB 이상 낮지 않을 때만 "averaging the pairs instead does as well: the gain is the free capacity, not the max"로 쓴다. 아니면 "and in one seed averaging the pairs did as well"로 남기거나 지운다.

- (a) 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 높으면: "; at the same training budget it scores +X / +Y dB above the ReLU network of the same width (mean of three seeds), and averaging the pairs instead does as well: the gain is the free capacity, not the max." 평균 결합이 maxout보다 어느 한 테스트셋에서라도 0.1 dB 이상 낮으면 뒷부분을 ", and +Z / +W dB above a control that averages the pairs"로 바꾼다.
- (b) 방향은 같지만 숫자를 줄이고 싶으면: 지금 문장에서 [SEEDS] [AVG]를 지우고 "(three seeds)"를 넣는다(평균 결합 구절은 위 조건대로).
- (c) 시드가 엇갈리거나 결과 전에 제출하면: 뒷부분을 지우고 "…doubles the parameters for 1% more cycles."로 끝낸다.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 보통 곱셈 수를 최소화하도록 설계되지만, 소형 가속기에서는 실행 시간이 다른 것으로 정해질 수 있다. 직접 설계한 Zynq XC7Z020 FPGA용 정수 CNN 코어(곱셈기 64개, 7비트 입력)에서, 측정된 병목이 가우시안 잡음 제거망의 설계를 어떻게 바꾸는지 보인다. 이전 보드 실행에서 본 보정 두 개를 넣어 네 망에서 보드와 0.003% 안에서 맞는 사이클 모델은, PC가 만든 창을 사이클당 값 하나씩 받는 이 구현이 입력 포트에 묶여 있음을 보인다. 값 K개의 창은 K 사이클이 들고 출력 채널은 64개까지 비용이 없어서, DnCNN 형태의 기준 망은 곱셈기 대부분을 놀린다. 그래서 연산량 기준으로는 낭비로 보이는 두 선택의 비용이 작다. 2×2 space-to-depth 입력은 6.4배 큰 망을 25% 적은 사이클에 넣는다. 은닉층 출력을 2배로 늘려 두 개씩 합치면(maxout) 파라미터가 2배가 되는 대신 사이클은 1%만 는다. 보드 연산을 재현한 양자화 인지 학습으로 화질 모델은 Set12에서 30.12 dB(σ = 25)로 같은 입력의 BM3D보다 높고, 속도 모델은 기준 망보다 2.63배 적은 사이클로 BM3D 수준이다. 네 가지 망을 Set12 한 장씩 보드에서 끝까지 실행해 비트 단위로 검증했다. 사이클 모델은 입력이 사이클당 2값이면 합치기가 공짜가 아니게 되고, 4값이거나(사이클당 4값을 받는 코어 변형에서 보드가 이 예측과 0.005% 안에서 맞았다) 라인 버퍼를 두면 6.4배 큰 망이 기준 망보다 느려진다고 예측한다. 고를 망은 측정한 병목에 따라 달라진다.

**[SEEDS] [AVG]** (2026-10-17: (c) 적용함) 영문과 같은 규칙: (a) "같은 학습 예산에서 같은 폭의 ReLU 망보다 +X / +Y dB 높고(시드 셋의 평균), 평균으로 합쳐도 같아서 이득은 max가 아니라 공짜 용량에서 온다" (b) 지금 문장에 "(시드 셋)"을 넣는다 (c) "…사이클은 1%만 는다."로 끝낸다.

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 30.00 / 28.94 (정수 PSNR; 속도 모델은 `dn_d10_c32_us_mo_fx_qat`), QAT 뒤 손실 0.04 dB 이내 | `denoise/export/<model>/int_eval.json`; 표는 `python denoise/results_table.py` |
| maxout 대 ReLU, 대 평균 결합 (재실험; (c)의 근거) | `dn_d10_c32_us{_mo,,_avg}_fx[_sN]_qat`의 int_eval (같은 120 epoch + QAT 15 epoch; ReLU·maxout 시드 1·2·3, 평균 결합 시드 2), 45채널 ReLU는 `dn_d10_c45_us_fx_qat` |
| B 대 A +0.29 / +0.22 (정수, QAT) | `dn_d10_c64_us_es_qat` 대 `dn_d7_c32_es` |
| BM3D 29.95 / 28.37, 클리핑 없이 29.98 / 28.62 | `denoise/baselines.json`, `denoise/bm3d_protocol.json` |
| DnCNN-S 같은 입력 30.35 / 28.89 (본문 표 I) | `denoise/dncnn_s_protocol.json` |
| 289 사이클/창, 675·668.5·1,323·1,775 사이클/px, 0 mismatches, 네 가지 망(학습 모델 일곱 개) | `denoise/board_runs/*_05.json` (B-32 ReLU는 `dn_d10_c32_us_fx_qat_05.json`) |
| 1.7% (보정 전) / 0.003% (보정 후), 41% 활용률 | `train_denoise.board_cycles_per_pixel` 대 `_measured` 대 `board_runs/` |
| 6.4배 파라미터 (300k / 47k), 1.6배 곱셈, 25% 적은 사이클 (1,323 / 1,775) | `denoise/README_KO.md` 표 |
| 같은 파라미터의 ReLU 망(45채널) 934 사이클/px(+38%), sparse 모드의 0이 아닌 곱셈 3.0배 | `train_denoise.board_cycles_per_pixel_measured`(45채널 형상), `board_runs/dn_d10_c32_us_{fx,mo_fx}_qat_05.json`의 `nonzero_fraction` |
| 2값/사이클 예측 (합치기 1.55배, B는 A의 0.82배; dense 상한 1.87배, 1.37배) | 05.png의 모든 창을 센 값, 적재 항 ⌈K/2⌉ (`denoise/wider_ports.py` → `wider_ports.json`, `PAPER_KO.md` 표 III) |
| 4값/사이클 (B는 A의 1.19배, 합치기 2.48배), 보드와 0.005% 안 | 예측은 같은 계수, 적재 항 ⌈K/4⌉ (`w4_prediction.json`, 7e81f6b에서 미리 커밋); 보드는 `denoise/board_runs/*_05_w4.json`, 비교는 `denoise/compare_w4.py` → `w4_measured.json`; RTL은 `denoise/sim_w4_layers.py` → `w4_rtl_sim.json` |
| 라인 버퍼 예측 (B는 A의 1.23배, 합치기 2.61배; dense 상한 A 827 대 B 1,206 사이클/px) | 같은 계수, 새 값은 창당 C_in개 (`wider_ports.json`) |
