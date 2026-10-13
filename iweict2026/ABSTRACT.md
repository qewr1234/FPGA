# IWEICT 2026 — 제목·초록 제출용 (마감 10월 16일)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 10월 23일까지 별도 업로드.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on a Feed-Bound Small-FPGA Integer Accelerator

## Abstract (English)

Efficient neural networks are usually designed to minimize the number of multiplications. On a small accelerator, however, the run time may not be set by the multiply count. We perform Gaussian image denoising on an integer CNN accelerator for a small FPGA (Zynq XC7Z020: 64 multipliers, a single bitstream, 7-bit inputs, ReLU outputs) and show how this difference changes the network design. A design-time cycle model, validated against board measurements to within 0.002%, shows that the core is bound by its input port: the cost of a layer is set by the number of input values per window, K, and is independent of the number of output channels up to 64. A baseline 7-layer DnCNN-style network uses only 41% of the multipliers. We therefore make two choices that look wasteful by FLOP count. First, a 2×2 space-to-depth input cuts the number of windows by four and doubles the channels: 1.6× the multiplications, but 25% fewer cycles and a higher PSNR. Second, the maxout activation, usually avoided because it doubles the computation, is implemented as extra output channels of every hidden layer. On the board, a 64-output maxout layer took 289 cycles per window, the same as a 32-output ReLU layer, and at an equal 675 cycles per pixel it gained +0.84 dB on Set12 and +0.59 dB on BSD68 over ReLU, on all 80 images. Quantization-aware training that reproduces the board's integer arithmetic reduced the integer conversion loss from 0.22 dB to 0.02 dB. At σ=25, the quality-first model reaches 30.12 dB on Set12 and 29.02 dB on BSD68 in integer arithmetic, above BM3D measured under the same clipped 7-bit input (29.95 / 28.37 dB) on both sets; the speed-first model runs 2.63× faster than the baseline network, matches BM3D on Set12 (29.95 dB) and exceeds it by 0.55 dB on BSD68. For both models, every layer's output on the board matched the integer model bit for bit.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 흔히 곱셈 수(연산량)를 줄이는 방향으로 설계된다. 그러나 소형 가속기에서 실제 실행 시간을 정하는 것은 연산량이 아닐 수 있다. 본 연구는 소형 FPGA(Zynq XC7Z020)의 정수 CNN 가속기(곱셈기 64개, 단일 비트스트림, 7비트 입력, ReLU 출력)로 영상 잡음 제거를 수행하며, 이 차이가 망 설계를 어떻게 바꾸는지 보인다. 설계 단계의 사이클 모델은 보드 실측과 0.002% 이내로 일치하며, 코어가 입력 포트에 묶여 비용이 층 입력 값의 수 K로 정해지고 출력 채널 수에는 64까지 무관함을 보인다. 기준 7층 망은 곱셈기의 41%만 쓴다. 이에 따라 연산량 기준으로는 손해인 두 가지 선택을 적용했다. 첫째, 영상을 2×2 위상으로 나누는 space-to-depth로 창 수를 1/4로 줄이고 채널을 2배로 늘렸다. 곱셈은 1.6배지만 사이클은 25% 줄고 화질은 올랐다. 둘째, 연산이 2배라는 이유로 쓰이지 않던 maxout 활성함수를 은닉층의 출력 채널로 구현했다. 보드 실측에서 출력 64채널의 maxout 층은 32채널 층과 같은 289 사이클/창이었고, 같은 675 사이클/픽셀에서 ReLU보다 Set12 +0.84 dB, BSD68 +0.59 dB 높았다(80장 모두). 보드 연산을 그대로 재현한 양자화 인지 학습은 정수 변환 손실을 0.22 dB에서 0.02 dB로 줄였다. 가우시안 잡음 σ=25에서 화질 우선 모델은 정수 기준 Set12 30.12 dB, BSD68 29.02 dB로 같은 입력 조건의 BM3D(29.95 / 28.37 dB)를 두 테스트셋 모두에서 넘었고, 속도 우선 모델은 기준 망보다 2.63배 빠르면서 Set12 29.95 dB로 BM3D와 같고 BSD68에서 0.55 dB 높았다. 두 모델 모두 보드에서 모든 층의 출력이 PC 정수 모델과 비트 단위로 일치했다.

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 29.95 / 28.91 (정수 PSNR) | `denoise/export/<model>/int_eval.json` (PC에서 생성, 업로드 예정) |
| BM3D 29.95 / 28.37 | `denoise/baselines.json` |
| 289 사이클/창, 675·1,323 사이클/px, 0 mismatches | `denoise/board_runs/*_qat_05.json` |
| 0.002% 모델 오차, 41% 활용률 | `train_denoise.board_cycles_per_pixel_measured` 대 `board_runs/` |
| maxout 대 ReLU +0.84 / +0.59 | `dn_d10_c32_us_mo_es` 대 `dn_d10_c32_us_es` int_eval |
| QAT 0.22 → 0.02 dB | `dn_d10_c32_us_mo_es` 대 `_qat` int_eval |
