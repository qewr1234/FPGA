# Continuous MAC v3 / v4 — RTL 검증 결과

Icarus Verilog 12.0 behavioral 시뮬레이션 결과입니다. FPGA 합성, timing, 자원, 보드 실측은 아닙니다.

동봉한 실행 증거는 `verification/included_run/`입니다:

| 파일 | 내용 |
|---|---|
| `sources/` | 그 실행에서 실제로 컴파일한 RTL·테스트벤치·스크립트 스냅샷 |
| `summary.json`, `summary.csv` | 164개 케이스 전체 결과 (설정, 통과 개수, cycle) |
| `<케이스>/rtl_cycles.csv` | 창별 start/end cycle 원본, 총 167,936행 |
| `<케이스>/simulation.log` | `vvp`가 출력한 PASS 문자열 |

케이스별 `summary.json`은 집계 `summary.json`에 그대로 들어 있어 중복이라 제외했고, `compile.log`는 164개가 모두 같은
timescale 경고 한 종류뿐이라 제외했습니다. 두 파일은 재실행하면 `build/stream_*/`에 다시 생깁니다.
전체 재생성은 `python scripts/run_stream_checks.py --suite full` 입니다 (결정론적이라 같은 숫자가 나옵니다).

## 검증 범위

- 164개 RTL 테스트 설정 (합성 벡터 141개 + 실제 VGG11 `features.3` 창 23개), 네 코어 모두 같은 테스트벤치.
- 정수 oracle과 비교한 출력 3,054,128개, 불일치 0.
- 창별 (start, end) edge와 독립 cycle 모델(`scripts/stream_model.py`) 비교 27,920행, 불일치 0.
- 실제 데이터: split별 512개 창 × dense/sparse 교대 = 1,024개 창을 back-to-back으로 스트림.
- 합성: P=1/2/3/4/8, DEPTH=1/2/3/4/8, K=1/9/27, COUT=1/9/17, T=1/2/3/4/5/8/9/16, stall 0/4/12,
  출력 ready 패턴 3종, 입력 gap, 전부 0 / 전부 127 / INT32 경계 입력.
  T는 2의 거듭제곱이 아닌 값과 T>K인 경우도 포함합니다.
- 프로토콜 검사: stall 중 출력 안정성, 그룹 내 발행 간격 1, 예약 슬롯 overflow/underflow/덮어쓰기, tuple bank 읽기/쓰기 충돌 없음,
  적재 안 된 bank 발행 없음, 비-idle 중 configuration 거부, 발행 cycle 총수(v4는 GROUPS × max bank)·입력 beat 총수,
  리셋 후 재실행(입력 대기 / 파이프라인 동작 / 출력 막힘 + 두 번째 창 적재 중).
- 검증 장치 자체 확인: gold 값 1개 훼손 → FATAL 검출, 모델 파이프라인 latency 1 cycle 오류 → 불일치 검출.

## 같은 스트림에서의 throughput (cycle / 창)

스트림 총 cycle(첫 start 수락 → 마지막 출력 수락)을 창 수 1,024로 나눈 값입니다. dense·sparse 창이 교대하므로 두 모드의 평균입니다.
네 코어가 같은 입력·가중치·bias·P·DEPTH·`m_ready` 패턴을 받습니다.

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

## v4 bank-parallel sparse issue

`banked_window_mac.sv`. tap `t`를 bank `t % T`에 두고 매 cycle 모든 bank에서 tuple 하나씩 발행합니다.
그룹당 cycle이 dense는 `ceil(K/T)`, sparse는 `max_b nnz_b`가 됩니다. 같은 스트림, 같은 `m_ready` 패턴:

| 데이터 | P | 출력 대기 | T | v4 banked | v3 overlap | v4 vs v3 | v4 vs v2 | 곱셈기 P×T |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| evaluation | 8 | 0/16 | 1 | 7,230.6 | 7,230.6 | ±0.00% | −7.53% | 8 |
| evaluation | 8 | 0/16 | 2 | 3,697.2 | 7,230.6 | **−48.87%** | −52.72% | 16 |
| evaluation | 8 | 0/16 | 4 | 1,910.7 | 7,230.6 | **−73.57%** | −75.56% | 32 |
| evaluation | 8 | 0/16 | 8 | 1,019.6 | 7,230.6 | **−85.90%** | −86.96% | 64 |
| evaluation | 8 | 12/16 | 4 | 1,910.7 | 7,230.6 | −73.57% | −75.62% | 32 |
| evaluation | 2 | 0/16 | 4 | 7,641.0 | 28,920.6 | −73.58% | −74.10% | 8 |
| calibration | 8 | 0/16 | 4 | 1,921.2 | — | — | — | 32 |

(calibration은 같은 조건의 v2/v3 실행이 없어 비교 칸을 비웠습니다. evaluation P=8 T=4와 같은 경향입니다.)

해석:

- **T=1은 v3와 스트림 전체에서 1 cycle 차이**입니다 (7,404,124 vs 7,404,123). 추가한 T-합 파이프라인 단이 마지막 창 배출에서만 1 cycle 비용이고
  정상 상태 throughput은 바꾸지 않습니다. v4가 v3의 상위집합이라는 확인입니다.
- 감소폭이 이상적인 1/T보다 작은 이유는 정적 인터리브의 bank 불균형입니다. sparse 창에서 evaluation 기준 T=2 6.2%, T=4 15.7%, T=8 35.1%
  (`verification/bank_parallel_projection.txt`). dense 창은 `ceil(K/T)`로 불균형이 없습니다.
- 사전 투영(sparse 전용, 창당 2,787 / 1,518 / 888)과 실측(dense·sparse 평균)이 같은 구조를 보입니다.
- stall 12/16에서 손실은 1,024개 창 전체에서 20 cycle입니다. 출력 대기가 다음 창 적재·계산과 겹칩니다.
- T=8, P=8에서도 sparse 창 발행(~885 cycle)이 K=576보다 커서 LOAD가 여전히 숨겨집니다.
  T를 더 키우면 발행이 576 아래로 내려가 **입력 대역폭이 병목**이 됩니다. 그때부터는 sparse 입력만 전송하거나 입력 폭을 넓혀야 합니다.

## 창별 latency는 커집니다

v3에서 창 하나의 start 수락 → 마지막 출력 수락은 evaluation P=8 기준 평균 14,470 cycle로, v2(창당 ~5,800~9,800)보다 깁니다.
창 w+1이 창 w의 계산이 끝날 때까지 bank에서 대기하기 때문입니다. v4도 같은 구조로, T=8에서 창당 latency는 평균 2,048 cycle입니다
(창당 throughput 1,019.6의 약 2배 — 항상 두 창이 진행 중).

이것은 파이프라인 구조의 당연한 결과이며, 비교는 throughput(창당 cycle)으로 해야 합니다. 개별 창의 응답 시간이 중요한 용도라면 v2가 맞습니다.

## 다음 판정

`latency = cycles / Fmax` 입니다. cycle 감소가 곧 시간 이득은 아닙니다.

- v3는 tuple RAM 1개 추가와 bank/window 태그 외에 새 제어 경로가 거의 없습니다 (`m_ready → release → issue` 경로는 v2와 같음). Fmax 손실이 작을 것으로 예상하지만 확인이 필요합니다.
- **v4는 곱셈기가 P×T개**이고 lane마다 T개 곱을 한 단에서 더합니다. Zynq-7020의 DSP는 220개이므로 P=8·T=8(64개)까지는 들어가지만,
  T-합 가산기 트리가 Fmax를 떨어뜨릴 수 있습니다. T가 커지면 가산기를 여러 단으로 쪼개야 할 수 있고, 그러면 파이프라인 단이 늘어납니다.
- weight RAM은 분할이라 총 bit 수는 같지만 **포트 수가 P×T개**가 되어 BRAM 할당이 늘 수 있습니다 (bank당 깊이 `GROUPS*ceil(K/T)`).

`scripts/synth_vivado.tcl`로 네 코어를 같은 part·클럭·P에서 OOC 합성/배치/배선해 `routed_utilization.rpt`와 `routed_timing.rpt`를 비교해야 합니다.
이 환경에는 Vivado가 없어 실행하지 못했습니다.
