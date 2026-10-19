# IWEICT 2026 제출용 제목·초록 (이 폴더의 논문 `PAPER_EN.md`)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 본문은 4쪽 docx(IEEE 템플릿)로 따로 올린다.
초록은 `PAPER_EN.md`의 Abstract와 글자 하나까지 같다(공백 기준 166단어). 제목을 바꾸면 논문 첫 줄(`# ...`)도 같이 바꾼다.

## Title (현재 논문 제목)

Reducing Bank-Synchronization Cycles of a Zero-Skipping FPGA CNN Core by Offline Channel Permutation

## Authors / affiliation

Lee Yoo Joon — School of Computer Science and Engineering, Yeungnam University; Information and Communication Engineering Major; Gyeongsan, Republic of Korea
(지도교수: 이름·소속·이메일 추가 예정)

## Abstract

A zero-skipping convolution core with lockstep input banks waits, in every window, for the bank with the most nonzero activations. In our integer core on a Zynq XC7Z020, where the channel count is a multiple of 4, the channel order decides which channels share a bank. We fit this order offline and fold it into the adjacent layers, leaving the bitstream and integer output unchanged; the layer shapes show where this cannot pay. At four values per cycle, two relabelings of a 32-channel denoiser cut the core cycles measured on one image (transcribed from run notes) by 7.02% and 7.60%, which a model pushed to GitHub before the export predicted to the cycle net of reported DMA stalls; under a protocol pushed before the fits, the pooled count fell on all ten networks. On this denoiser, a data-free skewed tap layout, counted after the study and not run on the board, saves more: 9.20% pooled over 79 images against 7.46% and 8.10% for the two relabelings.

**Keywords** — zero skipping, activation sparsity, load balancing, channel permutation, FPGA, CNN accelerator, cycle model

## 초록 (한국어, 확인용)

입력 뱅크가 동시에 움직이는 0 건너뛰기 합성곱 코어는 창마다 0이 아닌 활성값이 가장 많은 뱅크를 기다린다. Zynq XC7Z020 위의 우리 정수 코어에서는 채널 수가 4의 배수일 때 채널 순서가 어떤 채널들이 한 뱅크를 공유할지를 정한다. 이 순서를 오프라인으로 맞추고 인접 층에 접어 넣어, 비트스트림과 정수 출력은 바꾸지 않는다. 층의 모양만으로 이것이 이득을 낼 수 없는 곳을 알 수 있다. 사이클당 4값에서, 32채널 잡음 제거망의 두 재배치는 한 영상에서 측정한(실행 기록에서 옮겨 적은) 코어 사이클을 7.02%와 7.60% 줄였고, 내보내기 전에 GitHub에 올린 모델이 보고된 DMA 대기를 빼면 이를 사이클 단위로 맞혔다. 맞추기 전에 올린 프로토콜에서, 합산 사이클은 열 개 망 모두에서 줄었다. 이 잡음 제거망에서는 연구 뒤에 센(보드에서 돌리지 않은) 데이터 없는 skew 탭 배치가 더 많이 줄인다: 79장 합산 9.20%로, 두 재배치의 7.46%와 8.10%보다 크다.
