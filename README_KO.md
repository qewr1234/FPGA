# Continuous MAC v3 / v4 — 창 간 중첩 코어와 bank-parallel sparse 코어

`continuous_mac_rtl_v2` 패키지의 다음 단계입니다. v2는 **한 창 안에서** 출력 채널 그룹을 연속 발행했습니다.

| 코어 | 파일 | 요약 |
|---|---|---|
| v1 | `rtl/sparse_window_mac.sv` | 원본. 그룹마다 계산 → 출력 → 다음 그룹 |
| v2 | `rtl/continuous_window_mac.sv` | 원본. 창 안에서 그룹 연속 발행 (결과 슬롯 예약) |
| **v3** | `rtl/overlapped_window_mac.sv` | 창 간 중첩: 다음 창 입력 수신과 현재 창 계산을 겹침 |
| **v4** | `rtl/banked_window_mac.sv` | v3 + T개 tap bank에서 cycle당 T개 tuple 발행 (P×T 곱셈기) |

## v3: 창 간 중첩

v3(`overlapped_window_mac.sv`)는 v2의 예약 메커니즘을 **창 사이**로 확장합니다.

- tuple RAM을 2개 bank로 두어, 창 w가 계산·출력 중일 때 창 w+1의 K개 입력을 받습니다.
- 발행 엔진은 창 w의 마지막 그룹에서 창 w+1의 첫 그룹으로 bubble 없이 넘어갑니다(다음 창이 적재되어 있으면).
- 결과 슬롯 예약(DEPTH), 출력 순서, 산술, 인터페이스는 v2와 동일합니다. `start_ready`가 IDLE 외에도 bank가 비어 있으면 올라간다는 점만 다릅니다.
- 전부 0인 sparse 창은 별도 상태 없이 "곱을 0으로 강제한 pseudo tap" 한 개를 그룹당 발행해 같은 파이프라인으로 bias+ReLU를 냅니다.
- configuration은 적재 중/적재된 창이 없고 진행 중 결과가 없을 때(`core_idle`)만 받습니다. start와 동시에 오면 configuration이 우선합니다.

## 왜 이것인가

v2 검증 로그 기준 evaluation sparse 창의 cycle 구성:

| P | 총 cycle | LOAD (K=576) | issue (GROUPS × nnz) | 그 외 |
|--:|--:|--:|--:|--:|
| 2 | 21,558 | 576 (2.7%) | 20,976 (97.3%) | 6 |
| 8 | 5,832 | 576 (9.9%) | 5,244 (89.9%) | 12 |

v2가 없앤 그룹 오버헤드는 이제 창당 6~12 cycle뿐입니다. 남은 것은 LOAD와 issue이고, LOAD는 창 간 중첩으로 숨길 수 있습니다.
P가 클수록 LOAD 비중이 커지므로 개선 폭도 커집니다.

## v4: bank-parallel sparse issue

v3에서 남는 것은 issue(GROUPS × nnz)입니다. sparse 모드가 cycle을 더 못 줄이는 이유는 nonzero tap의 index가 불규칙해서
cycle당 weight RAM 읽기 1회, 즉 tuple 1개밖에 발행하지 못하기 때문입니다.

v4(`banked_window_mac.sv`)는 tap `t`를 bank `t % T`, row `t / T`에 둡니다.

- bank마다 tuple RAM이 따로 있고(창 버퍼 2개), lane마다 T개 weight RAM이 (group, row)로 인덱싱됩니다. weight 총 bit 수는 그대로입니다(분할, 복제 아님).
- 매 issue cycle에 모든 bank가 tuple 하나씩 읽어 P×T개 곱셈을 수행하고, lane별로 T개 곱을 더한 뒤 누산합니다(파이프라인 1단 추가).
- 그룹당 cycle = max_b(bank b의 tuple 수). dense는 ceil(K/T), sparse는 max_b nnz_b. tuple이 적은 bank는 곱을 0으로 강제합니다.
- 창 간 중첩, 슬롯 예약, 출력 순서, 인터페이스, configuration 규칙은 v3와 같습니다. T=1이면 v3와 같은 cycle + 1(추가 파이프라인 단)입니다.
- 정적 인터리브라 bank 불균형 손실이 있습니다. 실제 evaluation 창에서 T=2 6.2%, T=4 15.7%, T=8 35.1% (`scripts/bank_parallel_model.py`).

### v4를 읽을 때 주의

`(P, T)`로 돌린 v4는 곱셈기를 **P×T개** 씁니다. 그래서 기준선은 P 레인짜리 v3가 아니라 **P×T 레인짜리 v3**입니다.
곱셈기 수를 맞춰 재보면 이 레이어(COUT=128)에서는 모든 예산에서 v3 쪽이 빠르고, 초과분은 T에만 의존합니다
(T=2 +2.3%, T=4 +5.1~5.7%, T=8 +12.0%). v3는 P=128에서 창당 577.3 cycle로 입력 벽(K=576)에 닿고, v4도 같은 벽입니다.

따라서 cycle만으로는 T-banking을 정당화할 수 없습니다. T가 필요한 경우는 (a) COUT이 작아 P가 먼저 막히는 레이어,
(b) 같은 곱셈기 수에서 P축의 출력 mux·결과 플립플롭 비용이 T축의 가산기 트리·RAM 조각화보다 클 때 — 둘뿐이고,
(b)는 합성으로만 판정됩니다. 숫자와 근거는 `RESULTS_KO.md`의 "같은 곱셈기 수에서의 비교"에 있습니다.

## 실행

Python 3.9+, Icarus Verilog(`iverilog`, `vvp`)가 필요합니다.

```
python scripts/run_stream_checks.py --suite smoke --jobs 4   # 합성 벡터 141개 설정
python scripts/run_stream_checks.py --suite full  --jobs 4   # + 실제 VGG11 창 26개 설정 (총 167개)
python scripts/make_results.py build/stream_<stamp>            # 비교표
```

`sim/tb_stream_compare.sv`는 창을 **back-to-back**으로 흘립니다. 마지막 입력 beat를 내린 같은 negedge에 다음 start를 올리므로
중첩이 가능한 코어는 중첩하고, v1/v2는 `start_ready`를 낮춰 직렬로 처리됩니다. 네 코어가 같은 스트림, 같은 `m_ready` 패턴을 받습니다.
`IMPL=0..3`으로 코어를, `T`로 v4의 bank 수를 고릅니다.

측정값: 창별 start 수락 edge와 마지막 출력 수락 edge. 스트림 전체 cycle = `end[last] - start[0]`.
중첩 코어는 창당 latency(end−start)가 대기 시간 때문에 커질 수 있으므로 **throughput(총 cycle / 창 수)** 으로 비교해야 합니다.

`scripts/stream_model.py`는 네 코어의 프로토콜을 edge 단위로 다시 구현한 독립 cycle 모델입니다. 모든 창의 (start, end)가 RTL과 일치해야 PASS입니다.
같은 사람이 작성한 두 번째 구현이므로 "독립"의 강도는 v2 패키지의 해석적 모델과 같은 수준입니다.

검사 항목: 출력값(정수 oracle), 출력 순서/`m_last`, stall 중 출력 안정성, 그룹 내 발행 간격 1, 예약 overflow/underflow/덮어쓰기,
tuple bank 읽기/쓰기 충돌 없음, 적재되지 않은 bank 발행 없음, 비-idle 중 configuration 거부, 발행 cycle 총수(v4는 GROUPS × max bank), 입력 beat 총수,
리셋(입력 대기 중 / 파이프라인 동작 중 / 출력 막힌 상태 + v3/v4는 두 번째 창 적재 중) 후 재실행.
v4는 T=1,2,4,8 외에 3,5,9,16 같은 2의 거듭제곱이 아닌 T도 테스트합니다.

full 스위트에는 곱셈기 수를 맞춘 비교 케이스가 들어 있습니다: v3 `P=64`·`P=128`과 v4 `P=16,T=4`.
v4 `(P,T)`의 기준선은 `P×T` 레인짜리 v3이므로, 그 짝이 없으면 v4 수치를 해석할 수 없습니다.

## 결과

`RESULTS_KO.md`를 보세요. 동봉 실행 로그는 `verification/`에 있습니다.

## Vivado OOC 합성 (사용자 PC에서 실행)

이 환경에는 Vivado가 없어 실행하지 못했습니다. `scripts/synth_vivado.tcl`은 v2 패키지의 흐름에 v3/v4를 추가한 것입니다.

```tcl
cd {C:/fpga/FPGA}
set ::env(CNN_P) 8
set ::env(CNN_DEPTH) 2
set ::env(CNN_T) 4
set ::env(CNN_CLOCK_NS) 10.0
source scripts/synth_vivado.tcl
```

또는 Vivado 명령 환경에서 `RUN_SYNTH.cmd`. 결과 `build/ooc_*/<core>/routed_utilization.rpt`, `routed_timing.rpt`를 네 코어에 대해 비교합니다.
`CNN_CORES`로 일부 코어만 돌릴 수 있습니다. 기본 part `xc7z020clg484-1`은 임시값입니다.

**가장 먼저 돌려야 할 것은 곱셈기 64개짜리 세 구성입니다** — v3 `P=64,T=1` / v4 `P=16,T=4` / v4 `P=8,T=8`.
cycle은 각각 910.7 / 956.8 / 1,019.6이므로, v4가 이기려면 그 열세를 넘는 Fmax 우위가 나와야 합니다.
이것이 이 패키지의 유일한 미결 쟁점입니다.

## 범위 밖

Vivado 합성/배치배선, Fmax, 자원, 전력, AXI/DMA, 전체 CNN 시간, 보드 동작은 이 패키지에서 확인하지 않았습니다.
v4는 곱셈기가 P×T배이고 T개 곱의 합이 한 단에 들어가므로, Fmax와 DSP 소모를 합성으로 확인하기 전에는 cycle 감소를 시간 이득으로 주장하면 안 됩니다.
곱셈기 수를 맞추면 이 레이어에서 v4는 v3보다 cycle이 많으므로(위 "v4를 읽을 때 주의"), **현재 v4를 지지하는 측정값은 없습니다.**
COUT이 작아 P가 막히는 레이어는 이 패키지의 데이터로 다루지 않았습니다.
