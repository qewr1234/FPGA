# IWEICT 2026 제출용 제목·초록 (이 폴더의 논문 `PAPER_EN.md`)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 본문은 4쪽 docx(IEEE 템플릿)로 따로 올린다.

2026-10-19 판(저녁): 저자가 제목을 "Bank Layout Optimization for Zero-Skipping FPGA CNNs"로 바꾸고 초록 둘째 문장을 고쳤다(빠진 동사 "we derive"를 넣음). 보드 결과(PROTOCOL_2 c18fc8f, 부록 L3 1a327f7)를 넣어, 네 영상의 보드 절감(재배치 5.9–9.0%, skew 7.3–10.0%, 조합 7.9–10.7%)과 예측 일치(180개 층 중 176개 정확, 나머지 넷은 1사이클 차이)로 문장을 바꿨다. 제출 폼의 제목·초록도 이것으로 바꿔야 한다. 숫자의 출처: `board_measured_2.json`, `board_measured_3.json` (`runs.*.total.cycles`, `summary`).

2026-10-19 판(오후): 사전등록 2(951c8f1)의 결과(4a93e08: H4–H6 성립)를 넣어, 비교를 세 배치(재배치, skew, 조합)로 넓혔다. skew와 조합은 count이며 보드 실행은 진행 중이다. 숫자의 출처에 `results_2.json`(조합 9.93%, 아홉 망)을 더한다.

2026-10-19 판: 적대적 리뷰의 첫 지적(데이터 없는 skew가 제안한 순열을 이긴다)에 맞춰, 주제를 "채널 순열"에서
"뱅크 레이아웃이 언제 이득인가"로 바꿨다. 초록은 지금 있는 근거만 쓴다: 보드에서 잰 것은 두 재배치(Original 대비),
skew는 79장 count다. skew의 보드 실행(`PROTOCOL_2.md`)이 예측대로 나오면 최종본(10/23)에서 그 문장을 측정으로 바꾼다.
본문(`PAPER_EN.md`)은 이 제목·초록에 맞춰 고친다. 숫자의 출처: 7.02% / 7.60% `b32_board.json`(보드 값은
`board_transcribed.json`; 원본 보고서는 `RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd`로 커밋 예정), 9.20% `skew_count.json`,
7.46% / 8.10% `baselines.json`(79장), 열 개 망 `results.json`.

## Title

Bank Layout Optimization for Zero-Skipping FPGA CNNs

## Authors / affiliation

Lee Yoo Joon — School of Computer Science and Engineering, Yeungnam University; Information and Communication Engineering Major; Gyeongsan, Republic of Korea
*Gyu Sang Choi (최규상) — School of Computer Science and Engineering, Yeungnam University; Information and Communication Engineering Major; Gyeongsan, Republic of Korea (지도교수, 교신저자 표시 *는 저자가 붙임)

## Abstract

A zero-skipping convolution core whose input banks run in lockstep waits, in every window, for the bank with the most nonzero activations, so the assignment of window taps to banks sets its cycle count. On our integer CNN core for a Zynq XC7Z020, we derive a shape-only condition necessary for any layout to change a layer's cycles. We compare three layouts that keep the bitstream and the integer output unchanged: a channel relabeling fitted offline and folded into the adjacent layers, a data-free skew that spreads each channel's taps over the banks, and the two combined. At four values per cycle, on four test images of a 32-channel denoiser, the board measured core-cycle savings of 5.9–9.0% for two relabelings, 7.3–10.0% for the skew and 7.9–10.7% for the combination, and predictions committed before the runs matched 176 of 180 layer counts to the cycle and the other four within one. In counts over 79 test images the skew saves 9.20% and the combination 9.93%, against 7.46% and 8.10% for the relabelings; under pre-registered protocols this order held on all nine networks whose channel count is a multiple of four, and no layout changed the count where the shape condition says it cannot.

**Keywords** — zero skipping, activation sparsity, load balancing, bank layout, channel permutation, FPGA, CNN accelerator, cycle model

## 초록 (한국어, 확인용)

입력 뱅크가 동시에 움직이는 0 건너뛰기 합성곱 코어는 창마다 0이 아닌 활성값이 가장 많은 뱅크를 기다리므로, 창의 탭을 뱅크에 어떻게 배치하느냐가 사이클을 정한다. Zynq XC7Z020 위의 우리 정수 CNN 코어에서, 어떤 배치든 층의 사이클을 바꾸려면 반드시 만족해야 하는, 층의 모양만으로 정해지는 조건을 유도한다. 비트스트림과 정수 출력을 그대로 두는 세 배치를 비교한다: 오프라인으로 맞춰 인접 층에 접어 넣는 채널 재배치, 각 채널의 탭을 뱅크들에 흩는 데이터 없는 skew, 그리고 둘의 조합이다. 사이클당 4값에서, 32채널 잡음 제거망의 테스트 영상 네 장에 대해 보드가 잰 코어 사이클 절감은 두 재배치가 5.9–9.0%, skew가 7.3–10.0%, 조합이 7.9–10.7%였고, 실행 전에 커밋한 예측은 180개 층 사이클 중 176개를 사이클 단위로 맞히고 나머지 넷도 1사이클 안에서 맞혔다. 79장 테스트 영상의 계산에서 skew는 9.20%, 조합은 9.93%를 줄여 재배치의 7.46%, 8.10%보다 크다. 사전등록한 프로토콜에서 이 순서는 채널 수가 4의 배수인 아홉 망 모두에서 성립했고, 모양 조건이 바뀔 수 없다고 한 곳에서는 어떤 배치도 사이클을 바꾸지 않았다.
