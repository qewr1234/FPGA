# IWEICT 2026 제출용 제목·초록 (이 폴더의 논문 `PAPER_EN.md`)

제출 폼(Microsoft Forms)에 넣는 항목: 논문 제목, 저자, 소속, 초록. 본문은 4쪽 docx(IEEE 템플릿)로 따로 올린다.

2026-10-20 판: 저자의 리뷰에 맞춰 초록을 다시 썼다. 아이디어(호스트가 탭의 뱅크를 정하므로 불균형을 소프트웨어로 줄인다)를 먼저 두고, 숫자는 셋만 남겼다: 79장 count에서 skew 9.2%, 조합 9.9%, 보드에서 실행 전에 고정한 모델이 180개 층 중 176개를 정확히 맞힘. 보드 절감 범위와 71/72는 본문(V-A, VII)에 있다. "아홉 망"은 "채널 수가 4의 배수인 시험한 모든 망"으로 썼다(45채널 망에서는 skew가 L0과 같다). 검증 뒤(같은 날) 세 곳을 고쳤다: 9.2%와 9.9%가 W = 4, 79장 호스트 에뮬레이션 count임을 밝혔고, "호스트가 정한다"는 호스트가 창을 만드는 경우로 한정했고, 176/180 뒤에는 "나머지 넷도 1사이클 안"을 붙였다(처음 돌린 L2·L3은 72개 중 71개가 정확해서, "처음 돌린 배치도 포함"이라는 표현은 과장이었다). 제출 폼의 초록도 이것으로 바꿔야 한다. 숫자의 출처: 9.20% `skew_count.json`·`results_2.json`(L2), 9.93% `results_2.json`(L3), 176/180 `board_measured_2.json`·`board_measured_3.json` `summary`.

2026-10-19 판(저녁): 저자가 제목을 "Bank Layout Optimization for Zero-Skipping FPGA CNNs"로 바꾸고 초록 둘째 문장을 고쳤다(빠진 동사 "we derive"를 넣음). 보드 결과(PROTOCOL_2 c18fc8f, 부록 L3 1a327f7)를 넣어, 네 영상의 보드 절감(재배치 5.9–9.0%, skew 7.3–10.0%, 조합 7.9–10.7%)과 예측 일치(180개 층 중 176개 정확, 처음 돌린 skew와 조합은 72개 중 71개, 나머지 넷은 1사이클 차이)로 문장을 바꿨다. 검증 뒤 둘째 문장의 "cycles"를 "cycle count"로 바꿨다(모양 조건이 정하는 것은 count이고, fill-and-drain은 마지막 창에 따라 몇 사이클 달라질 수 있다). 제출 폼의 제목·초록도 이것으로 바꿔야 한다. 숫자의 출처: `board_measured_2.json`, `board_measured_3.json` (`runs.*.total.cycles`, `summary`).

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

Zero-skipping CNN accelerators often split each convolution window over parallel banks that advance in lockstep, so every window waits for the bank holding the most nonzero activations. When the host builds the windows, it also decides which bank each tap goes to, so the imbalance can be reduced in software: an offline layout of the taps changes the cycle count but neither the bitstream nor the integer output. On an integer CNN core for a Zynq XC7Z020 we give a test, from the layer shapes alone, of where any layout can gain, and compare three layouts: a channel relabeling fitted to activation statistics and folded into the weights, a data-free skew that spreads each channel's taps over the banks, and the two combined. In host emulation over 79 test images of a denoising CNN, at four window values per cycle, the skew cuts the core cycles by 9.2%, more than the fitted relabeling, and the combination by 9.9%; this order held on every tested network whose channel count is a multiple of four. On the board, a cycle model fixed before the runs predicted the cycles of 176 of 180 layers exactly and the other four within one cycle.

**Keywords** — zero skipping, activation sparsity, load balancing, bank layout, channel permutation, FPGA, CNN accelerator, cycle model

## 초록 (한국어, 확인용)

제로 스킵 CNN 가속기는 흔히 합성곱 창 하나를 함께 움직이는(lockstep) 여러 뱅크에 나누므로, 창마다 0이 아닌 활성값이 가장 많은 뱅크를 기다린다. 호스트가 창을 만드는 경우에는 각 탭을 어느 뱅크에 보낼지도 호스트가 정하므로, 이 불균형은 소프트웨어로 줄일 수 있다: 탭의 오프라인 배치는 사이클 수를 바꾸지만 비트스트림도 정수 출력도 바꾸지 않는다. Zynq XC7Z020용 정수 CNN 코어에서, 어떤 배치든 이득을 볼 수 있는 곳을 층의 모양만으로 판정하는 조건을 주고, 세 배치를 비교한다: 활성값 통계에 맞춰 가중치에 접어 넣는 채널 재배치, 각 채널의 탭을 뱅크들에 흩는 데이터 없는 skew, 그리고 둘의 조합. 잡음 제거 CNN의 테스트 영상 79장에 대한 호스트 에뮬레이션에서, 사이클당 4값일 때 skew는 코어 사이클을 9.2% 줄여 맞춘 재배치보다 많이 줄였고, 조합은 9.9% 줄였다; 이 순서는 채널 수가 4의 배수인 시험한 모든 망에서 성립했다. 보드에서는 실행 전에 고정한 사이클 모델이 180개 층 중 176개 층의 사이클을 정확히 맞혔고, 나머지 넷도 1사이클 안이었다.
