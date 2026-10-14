# IWEICT 2026 — 제목·초록 제출용

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 논문 본문(4쪽, IEEE 템플릿)은 별도 업로드. 웹사이트 기준 초록 10월 16일, 최종본 10월 23일(2026-10-15 확인; 저자가 받은 안내로는 초록이 10월 19일로 연장).

2026-10-15 판: 감사에서 확인된 오류를 고쳤다. 보드 검증 범위를 "다섯 모델"로, B 대 A 차이를 두 테스트셋 값으로, 입력 병목의 조건(PC가 만든 창을 사이클당 한 값씩 받는 구조)을 명시하고, 라인 버퍼 구조에서는 결론이 뒤집힌다는 예측을 마지막 문장으로 넣었다. maxout 문장은 같은 예산(120 epoch)으로 다시 학습 중인 ReLU·평균 결합·maxout 비교가 끝나면 (a)로, 끝나지 않으면 (b)로 넣는다. 이전 판의 +0.54 / +0.35 dB는 ReLU 망이 갱신 0.4만에서 조기 종료된 비교라 쓰지 않는다.

## Title

Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

## Abstract (English)

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. We denoise Gaussian noise (σ=25) on an integer CNN accelerator for a small FPGA (Zynq XC7Z020: 64 multipliers, one bitstream, 7-bit inputs, ReLU outputs) and show how the measured bottleneck changes the network design. A cycle model (within 1.7% at design time, within 0.003% after two corrections observed on earlier board runs) shows that this build, which receives host-built windows one 7-bit value per cycle, is bound by its input port: a layer costs K cycles per window, where K is the number of input values, whatever the number of output channels up to the multiplier count (64). A 7-layer DnCNN-style baseline therefore uses 41% of the multipliers. Two choices that look wasteful by FLOP count follow. A 2×2 space-to-depth input lets a 10-layer, 64-channel network (6.4× the parameters, 1.6× the multiplications) run in 25% fewer cycles than the baseline, 0.3 / 0.2 dB higher (Set12 / BSD68). Maxout, which doubles a layer's multiplications, becomes extra output channels of every hidden layer: on the board a 64-output maxout layer took 289 cycles per window, the same as a 32-output ReLU layer, **[MAXOUT]**. Quantization-aware training that reproduces the board's arithmetic brought every integer model within 0.04 dB of its float model. The quality-first integer model reaches 30.12 / 29.02 dB, above BM3D on the same clipped 7-bit input (29.95 / 28.37 dB; 29.98 / 28.62 dB unclipped); the speed-first model needs 2.63× fewer core cycles than the baseline at 29.95 / 28.91 dB. Five models ran one Set12 image end to end on the board, every layer matching the integer model bit for bit. With on-chip line buffers, the same cycle model predicts that both choices lose their advantage: the best network follows the bottleneck.

**[MAXOUT]** (a) 재실험이 끝나면: "and with the same training budget and quantization-aware training the maxout network scores +X / +Y dB above the ReLU network for 1% more cycles per pixel, and +Z / +W dB above a control that averages the same pairs instead of taking their maximum"

**[MAXOUT]** (b) 끝나지 않으면: "and for 1% more cycles per pixel the maxout network denoises better than the ReLU network of the same width"

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## 초록 (한국어, 확인용)

효율적인 신경망은 보통 곱셈 수를 최소화하도록 설계되지만, 소형 가속기에서는 실행 시간이 다른 것으로 정해질 수 있다. 본 연구는 소형 FPGA용 정수 CNN 가속기(Zynq XC7Z020: 곱셈기 64개, 단일 비트스트림, 7비트 입력, ReLU 출력)에서 가우시안 잡음(σ=25)을 제거하며, 측정된 병목이 망 설계를 어떻게 바꾸는지 보인다. 사이클 모델(설계 단계에서 1.7% 이내, 이전 보드 실행에서 관찰한 보정 두 개를 넣으면 0.003% 이내)은 PC가 만든 창을 사이클당 7비트 값 하나씩 받는 이 구현이 입력 포트에 묶여 있음을 보인다. 즉 한 층의 비용은 창당 K 사이클이며(K는 입력 값의 수), 출력 채널 수는 곱셈기 수(64)까지 비용에 영향을 주지 않는다. 그래서 7층 DnCNN 형태의 기준 망은 곱셈기의 41%만 쓴다. 여기서 연산량(FLOP) 기준으로는 낭비로 보이는 두 가지 선택이 나온다. 2×2 space-to-depth 입력은 10층 64채널 망(파라미터 6.4배, 곱셈 1.6배)을 기준 망보다 25% 적은 사이클에 돌리게 하며, 0.3 / 0.2 dB(Set12 / BSD68) 높다. 층의 곱셈을 2배로 만드는 maxout은 모든 은닉층의 추가 출력 채널이 된다. 보드에서 출력 64채널 maxout 층은 창당 289 사이클로 출력 32채널 ReLU 층과 같았고, **[MAXOUT]**. 보드 연산을 재현한 양자화 인지 학습은 모든 정수 모델을 float의 0.04 dB 안으로 가져왔다. 화질 우선 정수 모델은 30.12 / 29.02 dB로, 같은 클리핑 7비트 입력에서 측정한 BM3D(29.95 / 28.37 dB, 클리핑 없이는 29.98 / 28.62 dB)보다 높다. 속도 우선 모델은 기준 망보다 2.63배 적은 코어 사이클로 29.95 / 28.91 dB다. 다섯 모델이 Set12 한 장을 보드에서 끝까지 실행했고, 모든 층이 정수 모델과 비트 단위로 일치했다. 칩 안에 라인 버퍼를 두면 같은 사이클 모델은 두 선택의 이점이 모두 사라진다고 예측한다. 최적 망은 병목을 따라간다.

**[MAXOUT]** (a) "같은 학습 예산과 양자화 인지 학습에서 maxout 망은 픽셀당 1% 많은 사이클로 ReLU 망보다 +X / +Y dB, 같은 쌍을 max 대신 평균으로 합치는 대조군보다 +Z / +W dB 높다" (b) "픽셀당 1% 많은 사이클로 maxout 망은 같은 폭의 ReLU 망보다 잡음을 더 잘 제거한다"

## 수치의 출처

| 수치 | 파일 |
|---|---|
| 30.12 / 29.02, 29.95 / 28.91 (정수 PSNR), QAT 뒤 손실 0.04 dB 이내 | `denoise/export/<model>/int_eval.json`; 표는 `python denoise/results_table.py` |
| maxout 대 ReLU, 대 평균 결합 (재실험) | `dn_d10_c32_us_mo_fx_qat`, `dn_d10_c32_us_fx_qat`, `dn_d10_c32_us_avg_fx_qat`의 int_eval (같은 120 epoch + QAT 15 epoch) |
| B 대 A +0.29 / +0.22 (정수, QAT) | `dn_d10_c64_us_es_qat` 대 `dn_d7_c32_es` |
| BM3D 29.95 / 28.37, 클리핑 없이 29.98 / 28.62 | `denoise/baselines.json`, `denoise/bm3d_protocol.json` |
| DnCNN-S 같은 입력 30.35 / 28.89 (본문 표 I) | `denoise/dncnn_s_protocol.json` |
| 289 사이클/창, 675·1,323·1,775 사이클/px, 0 mismatches, 다섯 모델 | `denoise/board_runs/*_05.json` (B-32 ReLU의 669는 보정 모델, 보드 미실행) |
| 1.7% (보정 전) / 0.003% (보정 후), 41% 활용률 | `train_denoise.board_cycles_per_pixel` 대 `_measured` 대 `board_runs/` |
| 6.4배 파라미터 (300k / 47k), 1.6배 곱셈, 25% 적은 사이클 (1,323 / 1,775) | `denoise/README_KO.md` 표 |
| 라인 버퍼 예측 (maxout 289 대 ReLU 145 사이클/창, A 833 대 B 1,208 사이클/px) | dense 사이클 모델, 새 값은 창당 C_in개 (README "병목의 출처") |
