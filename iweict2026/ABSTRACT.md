# IWEICT 2026 — 제목·초록 제출용 (마감 10월 16일)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 10월 23일까지 별도 업로드.

심사 패널(6개 관점) 검증 뒤 고친 판: maxout 수치를 같은 학습·QAT 조건의 정수 쌍으로, 사이클 모델 정확도를 보정 전·후로, 보드 비트 일치를 실제 범위(모델당 Set12 한 장)로, BM3D를 클리핑 전·후 두 값으로 적었다. 2026-10-14: ReLU 모델에도 QAT 15 epoch을 돌려(정수 29.41 / 28.56 dB) maxout 수치를 QAT 대 QAT 정수 쌍 +0.54 / +0.35 dB로 바꿨다.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

## Abstract (English, 305 words)

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. We denoise Gaussian noise (σ=25) on an integer CNN accelerator for a small FPGA (Zynq XC7Z020: 64 multipliers, one bitstream, 7-bit inputs, ReLU outputs) and show how the measured bottleneck changes the network design. A cycle model (within 1.7% at design time, within 0.003% after two corrections observed on earlier board runs) shows that this build is bound by its input port, which accepts one 7-bit value per cycle: a layer costs K cycles per window, where K is the number of input values, whatever the number of output channels up to the multiplier count (64). A 7-layer DnCNN-style baseline therefore uses 41% of the multipliers. Two choices that look wasteful by FLOP count follow. A 2×2 space-to-depth input lets a 10-layer, 64-channel network (6.4× the parameters, 1.6× the multiplications) run in 25% fewer cycles than the baseline, 0.3 dB higher. Maxout, which doubles a layer's multiplications, becomes extra output channels of every hidden layer: on the board a 64-output maxout layer took 289 cycles per window, the same as a 32-output ReLU layer, and at equal 675 cycles per pixel the maxout network scores +0.54 / +0.35 dB (Set12 / BSD68) above the ReLU network after the same quantization-aware training. That training, which reproduces the board's arithmetic, brought every integer model within 0.04 dB of its float model. The quality-first integer model reaches 30.12 / 29.02 dB, above BM3D on the same clipped 7-bit input (29.95 / 28.37 dB; 29.98 / 28.62 dB unclipped); the speed-first model needs 2.63× fewer core cycles than the baseline at 29.95 / 28.91 dB. One Set12 image per model ran end to end on the board, every layer matching the integer model bit for bit.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 보통 곱셈 수를 최소화하도록 설계되지만, 소형 가속기에서는 실행 시간이 다른 것으로 정해질 수 있다. 본 연구는 소형 FPGA용 정수 CNN 가속기(Zynq XC7Z020: 곱셈기 64개, 단일 비트스트림, 7비트 입력, ReLU 출력)에서 가우시안 잡음(σ=25)을 제거하며, 측정된 병목이 망 설계를 어떻게 바꾸는지 보인다. 사이클 모델(설계 단계 1.7% 이내; 이전 보드 실행에서 관찰한 보정 두 개를 넣으면 세 망에서 0.003% 이내)은 이 구현이 사이클당 7비트 값 하나를 받는 입력 포트에 묶여 있음을 보인다. 즉 한 층의 비용은 창당 입력 값의 수 K 사이클이며, 출력 채널 수에는 곱셈기 수(P·T = 64)까지 무관하다. 그래서 기준이 되는 7층 DnCNN 형태의 망은 곱셈기의 41%만 쓴다. 연산량(FLOP) 기준으로는 낭비로 보이는 두 가지 선택을 했다. 2×2 space-to-depth 입력은 10층 64채널 망(파라미터 6.4배, 곱셈 1.6배)을 기준 망보다 25% 적은 사이클에 넣고, 0.3 dB 높다. 층의 곱셈을 2배로 만드는 maxout은 모든 은닉층의 추가 출력 채널로 구현했다. 보드에서 출력 64채널 maxout 층은 창당 289 사이클로 출력 32채널 ReLU 층과 같았고, 같은 675 사이클/픽셀에서 maxout 망은 같은 양자화 인지 학습을 거친 ReLU 망보다 +0.54 / +0.35 dB(Set12 / BSD68) 높다. 보드 연산을 재현한 그 학습은 모든 정수 모델을 float의 0.04 dB 안으로 가져왔다. 화질 우선 정수 모델은 30.12 / 29.02 dB로, 같은 클리핑 7비트 입력에서 측정한 BM3D(29.95 / 28.37 dB; 클리핑 없이 29.98 / 28.62 dB)보다 높다. 속도 우선 모델은 기준 망보다 2.63배 적은 코어 사이클로 29.95 / 28.91 dB다. 두 모델 모두 Set12 한 장을 보드에서 끝까지 실행했고, 모든 층이 정수 모델과 비트 단위로 일치했다.

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 29.95 / 28.91 (정수 PSNR), QAT 전 손실 0.22·0.04 | `denoise/export/<model>/int_eval.json` (PC에서 생성, 업로드 예정); 표는 `denoise/README_KO.md` |
| maxout 대 ReLU, QAT 대 QAT 정수 +0.54 / +0.35 | `dn_d10_c32_us_mo_es_qat` 29.95 / 28.91 대 `dn_d10_c32_us_es_qat` 29.41 / 28.56 (같은 학습·QAT 조건). 참고: float 쌍(QAT 전) +0.79 / +0.64, QAT 없는 정수 쌍 +0.64 / +0.35 |
| BM3D 29.95 / 28.37, 클리핑 없이 29.98 / 28.62 | `denoise/baselines.json`, `denoise/bm3d_protocol.json` |
| DnCNN-S 같은 입력 (표 I용) | `denoise/dncnn_s_protocol.json` |
| 289 사이클/창, 675·1,323 사이클/px, 0 mismatches | `denoise/board_runs/*_qat_05.json` |
| 1.7% (보정 전) / 0.003% (보정 후), 41% 활용률 | `train_denoise.board_cycles_per_pixel` 대 `_measured` 대 `board_runs/` |
| 6.4배 파라미터 (301k / 47k), 1.6배 곱셈, 25% 적은 사이클 (1,323 / 1,775) | `denoise/README_KO.md` 표 |
