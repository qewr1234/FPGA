# IWEICT 2026 제출용 제목·초록 (이 폴더의 논문 `PAPER_EN.md`)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 본문은 4쪽 docx(IEEE 템플릿)로 따로 올린다.

2026-10-19 판: 적대적 리뷰의 첫 지적(데이터 없는 skew가 제안한 순열을 이긴다)에 맞춰, 주제를 "채널 순열"에서
"뱅크 레이아웃이 언제 이득인가"로 바꿨다. 초록은 지금 있는 근거만 쓴다: 보드에서 잰 것은 두 재배치(Original 대비),
skew는 79장 count다. skew의 보드 실행(`PROTOCOL_2.md`)이 예측대로 나오면 최종본(10/23)에서 그 문장을 측정으로 바꾼다.
본문(`PAPER_EN.md`)은 이 제목·초록에 맞춰 고친다. 숫자의 출처: 7.02% / 7.60% `b32_board.json`(보드 값은
`board_transcribed.json`; 원본 보고서는 `RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd`로 커밋 예정), 9.20% `skew_count.json`,
7.46% / 8.10% `baselines.json`(79장), 열 개 망 `results.json`.

## Title

When Does Bank Layout Pay? Function-Preserving Channel Relabeling and Tap Skew on a Lockstep Zero-Skipping FPGA CNN Core

## Authors / affiliation

Lee Yoo Joon — School of Computer Science and Engineering, Yeungnam University; Information and Communication Engineering Major; Gyeongsan, Republic of Korea
(지도교수: 이름·소속·이메일 추가 예정)

## Abstract

A zero-skipping convolution core whose input banks run in lockstep waits, in every window, for the bank with the most nonzero activations, so the assignment of window taps to banks sets its cycle count. On our integer CNN core for a Zynq XC7Z020, a condition on the layer shapes alone tells where no tap-to-bank layout can change the cycles. We compare two layouts that keep the bitstream and the integer output unchanged: a channel relabeling fitted offline and folded into the adjacent layers, and a data-free skew that spreads each channel's taps over the banks. At four values per cycle, two relabelings of a 32-channel denoiser cut the core cycles measured on one image by 7.02% and 7.60%, as a model pushed before the export predicted to the cycle; under a pre-registered protocol the count fell on all ten networks studied and was unchanged wherever the shape condition says it must be. In counts over 79 test images the skew saves more than both relabelings: 9.20% against 7.46% and 8.10%.

**Keywords** — zero skipping, activation sparsity, load balancing, bank layout, channel permutation, FPGA, CNN accelerator, cycle model

## 초록 (한국어, 확인용)

입력 뱅크가 동시에 움직이는 0 건너뛰기 합성곱 코어는 창마다 0이 아닌 활성값이 가장 많은 뱅크를 기다리므로, 창의 탭을 뱅크에 어떻게 배치하느냐가 사이클을 정한다. Zynq XC7Z020 위의 우리 정수 CNN 코어에서, 층의 모양만으로 어떤 탭-뱅크 배치도 사이클을 바꿀 수 없는 곳을 판정하는 조건을 제시한다. 비트스트림과 정수 출력을 그대로 두는 두 배치를 비교한다: 오프라인으로 맞춰 인접 층에 접어 넣는 채널 재배치와, 각 채널의 탭을 뱅크들에 흩는 데이터 없는 skew다. 사이클당 4값에서, 32채널 잡음 제거망의 두 재배치는 한 영상에서 측정한 코어 사이클을 7.02%와 7.60% 줄였고, 내보내기 전에 올린 모델이 이를 사이클 단위로 맞혔다. 사전등록한 프로토콜에서 열 개 망 모두 사이클이 줄었고, 모양 조건이 0이라고 한 곳에서는 변하지 않았다. 79장 테스트 영상의 계산에서 skew는 두 재배치보다 더 줄인다: 9.20% 대 7.46%, 8.10%.
