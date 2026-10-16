# IWEICT 2026 — 제목·초록 제출용

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 별도 업로드. 웹사이트 기준 초록 10월 16일, 최종본 10월 23일(2026-10-15 확인; 저자가 받은 안내로는 초록이 10월 19일로 연장).

2026-10-16 판: 라인 버퍼 예측 문장을 정확하게 고쳤다. 두 선택의 이점이 "모두 사라진다"가 아니라, maxout은 더는 공짜가 아니고(ReLU의 약 2배 사이클) 망 B는 기준 망보다 느려진다(B-32 maxout은 라인 버퍼에서도 A보다 빠르다고 예측된다). 길이를 맞추려고 K 구절을 줄였다. 같은 예산(120 epoch + QAT 15 epoch)의 ReLU·maxout 결과는 정수 +0.37 / +0.26 dB(Set12 / BSD68, 한 시드)지만, 이 시드에서 ReLU 망이 epoch 26에 무너졌고 plateau 규칙이 회복 중에 학습률을 먼저 낮췄다(무너지기 전에는 두 망의 검증 PSNR이 같았다). 그래서 시드 2·3이 나오기 전에는 숫자를 초록에 넣지 않는다. 판단 규칙(결과를 보기 전에 정함): 모든 maxout 시드가 모든 ReLU 시드보다 두 테스트셋에서 높으면 (a), 아니면 (c). 시드 결과 전에 제출해야 하면 (c). 이전 판의 +0.54 / +0.35 dB는 ReLU 망이 갱신 0.4만에서 조기 종료된 비교라 쓰지 않는다.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

## Abstract (English)

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. We denoise Gaussian noise (σ=25) on our integer CNN accelerator for a Zynq XC7Z020 FPGA (64 multipliers, one bitstream, 7-bit inputs) and show how the measured bottleneck changes the network design. A cycle model, within 0.003% of the board after two corrections, shows that this build, which receives host-built windows one value per cycle, is bound by its input port: a window of K input values costs K cycles for up to 64 output channels. A 7-layer DnCNN-style baseline therefore uses 41% of the multipliers, and two choices that look wasteful by FLOP count pay off. A 2×2 space-to-depth input fits a 10-layer, 64-channel network (6.4× the parameters, 1.6× the multiplications) in 25% fewer cycles, 0.3 dB higher on Set12. Maxout, which doubles a layer's multiplications, becomes extra output channels: on the board a 64-output maxout layer took 289 cycles per window, as a 32-output ReLU layer did, **[MAXOUT]**. With quantization-aware training that reproduces the board's arithmetic, the quality-first integer model reaches 30.12 / 29.02 dB (Set12 / BSD68), above BM3D on the same clipped input (29.95 / 28.37 dB; 29.98 / 28.62 dB unclipped), and the speed-first model matches BM3D in 2.63× fewer cycles. Seven models were verified bit for bit on the board. With on-chip line buffers, the same model predicts that maxout stops being free and network B becomes slower than the baseline: the best network follows the bottleneck.

**[MAXOUT]** 자리에 아래 셋 중 하나를 넣는다(`PAPER_EN.md` 초록에는 지금 옛 문장 "and for 1% more cycles the maxout network denoises better than the ReLU network of the same width"가 들어 있다).

- (a) 시드가 모두 같은 방향이면: "and at the same training budget the maxout network scores +X / +Y dB above the ReLU network of the same width (mean of three seeds) for 1% more cycles" 뒤에, 평균 결합과의 차이가 0.1 dB 미만이면 ", as does averaging each pair instead: the gain comes from the free channels, not from the max"를 붙인다(시드 1에서 평균 결합은 maxout보다 검증 +0.02, float Set12 +0.03 dB 높았다). 두 테스트셋 모두 0.1 dB 이상 maxout이 높으면 ", and +Z / +W dB above a control that averages the same pairs"를 붙인다.
- (b) 숫자 없이 방향만: "and at the same training budget the maxout network denoises better than the ReLU network of the same width (three seeds) for 1% more cycles"
- (c) 시드가 엇갈리거나 결과 전에 제출하면: 이 절을 지우고 문장을 "..., as a 32-output ReLU layer did."로 끝낸다.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 보통 곱셈 수를 최소화하도록 설계되지만, 소형 가속기에서는 실행 시간이 다른 것으로 정해질 수 있다. 본 연구는 직접 설계한 Zynq XC7Z020 FPGA용 정수 CNN 가속기(곱셈기 64개, 단일 비트스트림, 7비트 입력)에서 가우시안 잡음(σ=25)을 제거하며, 측정된 병목이 망 설계를 어떻게 바꾸는지 보인다. 보정 두 개를 넣은 사이클 모델은 보드와 0.003% 안에서 맞으며, PC가 만든 창을 사이클당 값 하나씩 받는 이 구현이 입력 포트에 묶여 있음을 보인다. 즉 입력 값 K개의 창은 K 사이클이 들고, 출력 채널은 64개까지 비용이 없다. 그래서 7층 DnCNN 형태의 기준 망은 곱셈기의 41%만 쓰고, 연산량(FLOP) 기준으로는 낭비로 보이는 두 선택이 이득이 된다. 2×2 space-to-depth 입력은 10층 64채널 망(파라미터 6.4배, 곱셈 1.6배)을 25% 적은 사이클에 넣고, Set12에서 0.3 dB 높다. 층의 곱셈을 2배로 만드는 maxout은 추가 출력 채널이 된다. 보드에서 출력 64채널 maxout 층은 출력 32채널 ReLU 층과 같은 창당 289 사이클이었고, **[MAXOUT]**. 보드 연산을 재현한 양자화 인지 학습으로 화질 우선 정수 모델은 30.12 / 29.02 dB(Set12 / BSD68)에 이르러 같은 클리핑 입력의 BM3D(29.95 / 28.37 dB; 클리핑 없이 29.98 / 28.62 dB)보다 높고, 속도 우선 모델은 2.63배 적은 사이클로 BM3D 수준이다. 일곱 모델을 보드에서 비트 단위로 검증했다. 칩 안에 라인 버퍼를 두면 같은 모델은 maxout이 더는 공짜가 아니고 망 B가 기준 망보다 느려진다고 예측한다. 최적 망은 병목을 따라간다.

**[MAXOUT]** (a) "같은 학습 예산에서 maxout 망은 1% 많은 사이클로 같은 폭의 ReLU 망보다 +X / +Y dB 높다(시드 셋의 평균)" (b) "같은 학습 예산에서 1% 많은 사이클로 maxout 망은 같은 폭의 ReLU 망보다 잡음을 더 잘 제거한다(시드 셋)" (c) 이 절을 지우고 "…ReLU 층과 같은 창당 289 사이클이었다."로 끝낸다.

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 30.00 / 28.94 (정수 PSNR; 속도 모델은 `dn_d10_c32_us_mo_fx_qat`), QAT 뒤 손실 0.04 dB 이내 | `denoise/export/<model>/int_eval.json`; 표는 `python denoise/results_table.py` |
| maxout 대 ReLU, 대 평균 결합 (재실험) | `dn_d10_c32_us{_mo,,_avg}_fx[_sN]_qat`의 int_eval (같은 120 epoch + QAT 15 epoch, 시드 1·2·3) |
| B 대 A +0.29 / +0.22 (정수, QAT) | `dn_d10_c64_us_es_qat` 대 `dn_d7_c32_es` |
| BM3D 29.95 / 28.37, 클리핑 없이 29.98 / 28.62 | `denoise/baselines.json`, `denoise/bm3d_protocol.json` |
| DnCNN-S 같은 입력 30.35 / 28.89 (본문 표 I) | `denoise/dncnn_s_protocol.json` |
| 289 사이클/창, 675·668.5·1,323·1,775 사이클/px, 0 mismatches, 일곱 모델 | `denoise/board_runs/*_05.json` (B-32 ReLU는 `dn_d10_c32_us_fx_qat_05.json`) |
| 1.7% (보정 전) / 0.003% (보정 후), 41% 활용률 | `train_denoise.board_cycles_per_pixel` 대 `_measured` 대 `board_runs/` |
| 6.4배 파라미터 (300k / 47k), 1.6배 곱셈, 25% 적은 사이클 (1,323 / 1,775) | `denoise/README_KO.md` 표 |
| 라인 버퍼 예측 (maxout 289 대 ReLU 145 사이클/창, A 833 대 B 1,209 사이클/px) | dense 사이클 모델, 새 값은 창당 C_in개 (README "병목의 출처") |
