# Continuous MAC v3 — RTL 검증 결과

Icarus Verilog 12.0 behavioral 시뮬레이션 결과입니다. FPGA 합성, timing, 자원, 보드 실측은 아닙니다.
실행 로그와 소스 스냅샷은 `verification/included_run/`에 있습니다 (`summary.json`, 케이스별 `rtl_cycles.csv`, `simulation.log`).

## 검증 범위

- 116개 RTL 테스트 설정 (합성 벡터 100개 + 실제 VGG11 `features.3` 창 16개), 세 코어 모두 같은 테스트벤치.
- 정수 oracle과 비교한 출력 2,124,076개, 불일치 0.
- 창별 (start, end) edge와 독립 cycle 모델(`scripts/stream_model.py`) 비교 19,372행, 불일치 0.
- 실제 데이터: split별 512개 창 × dense/sparse 교대 = 1,024개 창을 back-to-back으로 스트림.
- 합성: P=1/2/4/8, DEPTH=1/2/3/4/8, K=1/9/27, COUT=1/9/17, stall 0/4/12, 출력 ready 패턴 3종, 입력 gap, 전부 0 / 전부 127 / INT32 경계 입력.
- 프로토콜 검사: stall 중 출력 안정성, 그룹 내 발행 간격 1, 예약 슬롯 overflow/underflow/덮어쓰기, tuple bank 읽기/쓰기 충돌 없음,
  적재 안 된 bank 발행 없음, 비-idle 중 configuration 거부, 발행 tap/입력 beat 총수, 리셋 후 재실행(입력 대기 / 파이프라인 동작 / 출력 막힘 + 두 번째 창 적재 중).
- 검증 장치 자체 확인: gold 값 1개 훼손 → FATAL 검출, 모델 파이프라인 latency 1 cycle 오류 → 불일치 검출.

## 같은 스트림에서의 throughput (cycle / 창)

스트림 총 cycle(첫 start 수락 → 마지막 출력 수락)을 창 수 1,024로 나눈 값입니다. dense·sparse 창이 교대하므로 두 모드의 평균입니다.
세 코어가 같은 입력·가중치·bias·P·DEPTH·`m_ready` 패턴을 받습니다.

| 데이터 | P | 출력 대기 | v1 serial | v2 continuous | v3 overlap | v3 vs v2 | v3 vs v1 |
|---|--:|--:|--:|--:|--:|--:|--:|
| calibration | 2 | 0/16 | 30,129.9 | 29,751.9 | 29,169.4 | −1.96% | −3.19% |
| evaluation | 2 | 0/16 | 29,881.1 | 29,503.1 | 28,920.6 | −1.97% | −3.21% |
| evaluation | 8 | 0/16 | 7,999.0 | 7,819.0 | 7,230.6 | **−7.53%** | −9.61% |
| evaluation | 8 | 12/16 | 8,307.7 | 7,838.0 | 7,230.6 | **−7.75%** | −12.96% |
| evaluation | 16 | 0/16 | — | 4,212.0 | 3,615.6 | **−14.16%** | — |
| evaluation | 32 | 0/16 | — | 2,420.5 | 1,808.1 | **−25.30%** | — |

v1/v2의 P=2, P=8 값은 v2 패키지 `RESULTS_KO.md`의 창별 평균과 일치합니다 (start 핸드셰이크 1 cycle 차이). 새 테스트벤치가 기존 측정을 재현합니다.

해석:

- v3가 줄이는 양은 창당 약 582 cycle = K(576) 입력 수신 + start 핸드셰이크입니다. P와 무관하게 거의 일정하고, P가 클수록 비율이 커집니다.
- 12/16 출력 stall에서 v3의 스트림 손실은 1,024개 창 전체에서 21 cycle입니다 (v2 창당 19, v1 창당 309). 출력 대기가 다음 창 적재와 겹칩니다.
- P=32에서 sparse 창의 계산(4그룹 × ~328 = ~1,312 cycle)이 여전히 K=576보다 크므로 LOAD가 완전히 숨겨집니다. P를 더 키우면 LOAD가 병목이 되어 v3의 이득은 절대량으로 고정되고, 그 다음은 입력 대역폭(제안 B 또는 입력 폭 확대)이 필요합니다.

## 창별 latency는 커집니다

v3에서 창 하나의 start 수락 → 마지막 출력 수락은 evaluation P=8 기준 평균 14,470 cycle로, v2(창당 ~5,800~9,800)보다 깁니다.
창 w+1이 창 w의 계산이 끝날 때까지 bank에서 대기하기 때문입니다. 이것은 파이프라인 구조의 당연한 결과이며,
비교는 throughput(창당 cycle)으로 해야 합니다. 개별 창의 응답 시간이 중요한 용도라면 v2가 맞습니다.

## 제안 B 투영 (RTL 없음)

`verification/bank_parallel_projection.txt`. evaluation, sparse 모드, v3 중첩 가정:

| P | T | 창당 cycle | v3 T=1 대비 | 곱셈기 P×T |
|--:|--:|--:|--:|--:|
| 8 | 1 | 5,246 | 0% | 8 |
| 8 | 2 | 2,787 | −46.9% | 16 |
| 8 | 4 | 1,518 | −71.1% | 32 |
| 8 | 8 | 888 | −83.1% | 64 |

정적 인터리브의 bank 불균형 손실: T=2 6.2%, T=4 15.7%, T=8 35.1%. RTL, 합성, timing 없이 숫자를 주장하면 안 됩니다.

## 다음 판정

`latency = cycles / Fmax` 입니다. v3는 tuple RAM 1개 추가와 bank/window 태그 외에 새 제어 경로가 거의 없습니다 (`m_ready → release → issue` 경로는 v2와 같음).
v2 패키지의 `synth_vivado.tcl`에 `overlapped_window_mac`을 추가해 세 코어의 자원과 timing을 같은 OOC 조건으로 비교해야 합니다.
