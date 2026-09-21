# 보드 브링업 — v3/v4 코어를 실제로 돌리기

대상: XC7Z020-CLG484 기반 Zynq 보드. 보드 파트는 PS(DDR·MIO·클럭) 프리셋만 정하므로,
같은 디바이스의 보드 파트면 일단 빌드는 됩니다. DDR이 실제로 다르면 보드에서 돌릴 때 드러납니다.

`window_mac_axis`(AXI-Stream 래퍼) + Zynq PS + AXI DMA로 실제 VGG11 `features.3` 창을 코어에 흘리고,
모든 출력을 정수 oracle과 대조하며, 코어 내부 cycle 카운터를 읽어 시뮬레이션 수치와 비교합니다.

## 무엇이 검증됐고 무엇이 아닌가

| 구성요소 | 상태 |
|---|---|
| 코어 4종 (`rtl/*_window_mac.sv`) | **검증됨** — 167케이스, 출력 3,447,344개 불일치 0 |
| AXI-Stream 래퍼 (`rtl/window_mac_axis.sv`) | **시뮬레이션 검증됨** — 28케이스, 코어 대비 cycle 오버헤드 0 |
| 보드 데이터 생성 (`scripts/export_board_data.py`) | **검증됨** — 시뮬레이션 벡터와 바이트 단위 대조 |
| 실행 스크립트 (`scripts/run_board_xsdb.tcl`) | **보드에서 완주함** — 불일치 0, cycle이 시뮬레이션과 일치 |
| PS 애플리케이션 (`sw/window_mac_test.c`) | 문법 검사만 — **미실행**. xsdb 경로로 대체되어 필요 없습니다 |
| Vivado 빌드 (`scripts/build_zedboard.tcl`) | **실행됨** — xc7z020clg484, v3 P=8 @100MHz, WNS +0.919 ns, 0 errors |
| 보드 로드 (`scripts/run_board.tcl`) | 미실행 — Vitis ELF 경로용 |

즉 **RTL 경로는 믿을 만하고, 툴체인 스크립트는 첫 실행에서 손볼 가능성이 큽니다.** 아래 "먼저 깨질 것들"을 보세요.

## 0단계 — 먼저 합성 (보드 불필요)

v3/v4 판정에 필요한 건 Fmax이고, 그건 보드 없이 나옵니다. 이걸 먼저 하세요.

```
RUN_SYNTH.cmd
```

`build/ooc_*/<core>/routed_timing.rpt`의 WNS로 Fmax를, `routed_utilization.rpt`로 자원을 봅니다.
여기서 나온 Fmax가 아래 1단계의 `CNN_CLOCK_MHZ` 상한을 정합니다.

## 1단계 — 비트스트림

탐색기에서 `RUN_BUILD_ZED.cmd`를 더블클릭하거나, 명령 프롬프트에서:

```
RUN_BUILD_ZED.cmd            :: v3, P=8, 100MHz (여기서 시작하세요)
RUN_BUILD_ZED.cmd 3 8 8 100  :: v4, P=8, T=8
RUN_BUILD_ZED.cmd 2 64 1 100 :: v3, P=64 (위와 같은 곱셈기 64개)
```

인자는 `IMPL P T CLOCK_MHZ` 순서입니다. Vivado Tcl 셸에서 직접 하시려면:

```tcl
cd {C:/fpga/FPGA}
set ::env(CNN_IMPL) 2        ;# 2 = v3 overlapped, 3 = v4 banked
set ::env(CNN_P) 8
set ::env(CNN_DEPTH) 2
set ::env(CNN_T) 4           ;# v4에서만 의미
set ::env(CNN_CLOCK_MHZ) 100
source scripts/build_zedboard.tcl
```

`build/zed_v3_p8_t4_<stamp>/`에 `system_wrapper.bit`과 `system_wrapper.xsa`가 나옵니다.
스크립트가 WNS를 출력하는데, **음수면 거기서 멈추고 클럭을 낮춰 다시 빌드하세요.** timing을 못 맞춘 비트스트림은
느린 게 아니라 틀린 값을 냅니다.

주소: `window_mac_axis` = `0x43C00000`, AXI DMA = `0x40400000`.

## 2단계 — 데이터 생성

```
python scripts/export_board_data.py --frames 512
```

`build/board/`에 `config.bin`(295,424 B), `input.bin`(589,824 B), `gold.bin`(524,288 B), `layout.json`이 생깁니다.
`input.bin`은 이미 창 순서대로(mode_seq=2면 프레임마다 dense·sparse 두 번) 펼쳐져 있어서 PS는 통째로 한 번 DMA하면 됩니다.

## 3단계 — 실행

**Vitis는 필요 없습니다.** PS 프로그램이 하는 일은 레지스터 몇 개 쓰고, DMA를 걸고,
메모리를 비교하는 것뿐이고 `xsdb`가 그걸 전부 할 수 있습니다. Vivado만 설치한 환경에는
ARM 크로스 컴파일러가 없어 `sw/window_mac_test.c`를 빌드할 수 없는데, 그래도 이 경로로 갑니다.

보드 USB(JTAG)를 연결하고:

```
C:\Vivado\2026.1\Vivado\bin\xsdb.bat
```

열린 셸에서:

```tcl
cd C:/fpga/FPGA
source scripts/run_board_xsdb.tcl
```

비트스트림을 올리고, PS를 초기화하고, DDR이 응답하는지 확인하고, 데이터 세 덩어리를 넣고,
설정을 스트리밍하고, 1,024창을 돌리고, 결과 131,072개를 `gold.bin`과 대조해 바로 출력합니다.
UART 터미널도 필요 없습니다 — 결과가 `xsdb` 콘솔에 나옵니다.

측정은 영향받지 않습니다. JTAG은 준비와 결과 회수에만 쓰이고, DMA를 건 다음부터는
코어가 fabric 클럭으로 돕니다. `CYCLES`는 코어 내부 카운터 값입니다.

빌드 디렉터리를 직접 고르려면:

```tcl
set ::env(WM_BUILD) C:/fpga/FPGA/build/zed_v3_p8_t4_1789907417
```

### 이 스크립트는 보드 없이 검증했습니다

`scripts/test_run_board_xsdb.tcl`이 `xsdb`를 흉내 낸 스탠드인 위에서 실행 스크립트를 돌립니다.
정상 경로는 PASS에 도달해야 하고, 잘못된 비트스트림·DDR 무응답·설정 스트림 절단·DMA 에러·
결과 불일치·데이터 크기 불일치는 각각 자기 메시지로 멈춰야 합니다. `loadhw`가 `ps7_init`을
정의하지 않는 경우의 복구 경로도 포함해 10개 케이스 전부 통과합니다.

```
python scripts/export_board_data.py --frames 512
tclsh scripts/test_run_board_xsdb.tcl
```

검증된 것은 스크립트의 논리와 가드입니다. `connect` / `fpga` / `loadhw` / `ps7_init`은
스탠드인이므로, 실제 `xsdb`가 이 명령들을 어떻게 받는지는 보드에서 처음 확인됩니다.

### Vitis가 설치돼 있다면

`sw/window_mac_test.c`를 빌드해 쓰셔도 됩니다. 같은 일을 하고, 결과를 UART(115200)로 냅니다.
`system_wrapper.xsa`로 플랫폼을 만들고 빈 C 애플리케이션의 소스를 이 파일로 바꾸면 됩니다.
그 경우 로드는 `scripts/run_board.tcl`이 합니다.

## 하드웨어 결과 (XC7Z020-CLG484, 2026-09-20)

v3 `overlapped_window_mac`, P=8, 100 MHz, 1,024창:

```
MISMATCHES     : 0
CYCLES         : 7404123
  per window   : 7230.59
IN_STALL       : 0
OUT_STALL      : 0
RESULT: PASS -- core bound.
```

`7,404,123`은 `verification/included_run/summary.json`의 `total_cycles`와 **같은 값**입니다.
출력 131,072개가 전부 정수 oracle과 일치하고, 두 stall 카운터가 0이므로 이 수치는
메모리 경로가 아니라 코어를 측정한 것입니다. 100 MHz에서 창당 72.3 µs.

## 결과 읽는 법

```
MISMATCHES     : 0
CYCLES         : 7404123
  per window   : 7230.59
IN_STALL       : 0
OUT_STALL      : 0
RESULT: PASS -- core bound.
```

순서대로 봅니다:

1. **`MISMATCHES`가 0이 아니면 나머지는 의미 없습니다.** 값이 틀린 것이고, 대개 timing 미달이거나 DMA 정렬 문제입니다.
2. **`IN_STALL`/`OUT_STALL`이 0이어야 `CYCLES`가 시뮬레이션과 비교 가능합니다.** 0이 아니면 그만큼 코어가 메모리 경로를
   기다린 것이고, 그 실행은 코어가 아니라 DMA를 측정한 것입니다. 작게 나오면 `CYCLES − IN_STALL − OUT_STALL`이
   시뮬레이션 값 근처인지로 대략 확인할 수 있습니다.
3. 그 다음에야 `CYCLES`를 아래 표와 비교합니다.

### 기대값 (evaluation, 1,024창, DEPTH=2)

`verification/included_run/summary.json`의 `total_cycles`와 같은 값입니다.

| 구성 | CNN_IMPL | CNN_P | CNN_T | 곱셈기 | CYCLES | cycle/창 |
|---|--:|--:|--:|--:|--:|--:|
| v3 | 2 | 8 | — | 8 | 7,404,123 | 7,230.6 |
| v4 | 3 | 8 | 4 | 32 | 1,956,540 | 1,910.7 |
| v4 | 3 | 8 | 8 | 64 | 1,044,037 | 1,019.6 |
| **v3** | 2 | 64 | — | **64** | **932,604** | **910.7** |
| **v4** | 3 | 16 | 4 | **64** | **979,737** | **956.8** |
| v3 | 2 | 128 | — | 128 | 591,194 | 577.3 (입력 벽) |

굵은 두 줄이 같은 곱셈기 예산의 v3/v4 쌍입니다. **보드에서 진짜 알고 싶은 건 이 둘의 `cycles / Fmax`입니다.**
cycle은 이미 v3가 10.7% 앞서 있으므로, v4가 이기려면 Fmax에서 그만큼을 뒤집어야 합니다.

## 권장 순서

1. **v3, P=8, 100MHz 먼저.** 곱셈기 8개짜리라 자원·timing 여유가 크고, 전체 사슬(비트스트림 → DMA → 값 일치)을
   검증하는 게 목적입니다. 여기서 `MISMATCHES 0`, `CYCLES 7,404,123`이 나오면 시스템이 맞는 겁니다.
2. 그 다음 v4 P=8 T=4 → T=8로 올리며 자원과 timing이 어디서 무너지는지 봅니다.
3. 마지막에 iso-곱셈기 쌍(v3 P=64 vs v4 P=16 T=4)을 같은 클럭으로 빌드해 비교합니다.

P=64/P=128은 7020에서 자원과 Fmax가 빡빡할 수 있습니다. weight RAM 포트가 P개로 늘고 출력 mux가 `DEPTH×P:1`이 됩니다
(P=128, DEPTH=2면 256:1 32bit). 안 들어가거나 timing이 안 맞으면 그 자체가 유의미한 결과이니 기록하세요 —
"v3의 P 확장은 이 칩에서 한계가 있다"가 바로 v4를 정당화하는 근거가 됩니다.

## 먼저 깨질 것들

빌드 스크립트가 한 번도 실행된 적이 없으므로, 순서대로 의심하세요.

| 증상 | 원인 / 대응 |
|---|---|
| `invalid command name "ps7_init"` | `loadhw`가 정의해주는 게 정상인데 안 해주는 설치가 있습니다. 스크립트가 빌드 트리에서 `ps7_init.tcl`(PS7 IP가 생성)을 찾아 직접 `source` 합니다. 그것도 없으면 XSA(zip) 안의 사본을 꺼냅니다 |
| Vitis에 `Create Platform Component`가 없음 | Vivado 에디션만 설치된 것입니다. Embedded 개발 도구(ARM 컴파일러)가 없습니다. **설치할 필요 없습니다** — 3단계의 `xsdb` 경로를 쓰세요 |
| `Vivado was not found` | Vivado는 설치해도 PATH에 안 잡힙니다. `.cmd`가 흔한 설치 경로를 뒤지지만 못 찾으면 `set XILINX_VIVADO=C:\Xilinx\Vivado\2023.2` 후 다시 실행하거나, 시작 메뉴의 **Vivado Tcl Shell**에서 `source` 하세요 |
| 보드 파트 관련 에러 | **먼저 `get_board_parts`를 치세요.** 설치된 목록이 나옵니다. 님 FPGA 파트(`xc7z020clg484`)와 같은 게 있으면 그걸 쓰면 됩니다 — `xilinx.com:zc702:part0:1.4`가 바로 그것입니다. 스크립트가 이제 자동으로 같은 파트의 보드를 찾아 씁니다. 직접 지정하려면 `set ::env(CNN_BOARD) <이름>` |
| `No installed board part uses xc7z020clg484` | 같은 디바이스 보드가 하나도 없는 경우. `Tools → Vivado Store → Boards`에서 ZC702 등을 설치하세요 |
| BD에서 `window_mac_top`의 AXI 인터페이스 미인식 | 모듈 참조의 인터페이스 추론 실패. BD에서 해당 셀 우클릭 → 인터페이스 수동 지정, 또는 `ipx::package_project`로 IP 패키징 후 사용 |
| `aclk`/`aresetn` 미연결 | 스크립트가 `proc_sys_reset` 셀 이름을 못 찾은 경우. BD에서 `FCLK_CLK0`와 `peripheral_aresetn`을 직접 연결 |
| DMA 전송이 끝나지 않음 | `c_sg_length_width`가 작으면 전송 길이가 잘립니다. 스크립트는 26으로 설정하지만 IP 버전에 따라 이름이 다를 수 있으니 DMA 설정에서 확인 |
| `CFGCOUNT`가 73,856이 아님 | config 스트림이 중간에 끊긴 것. `config.bin` 크기(295,424 B)와 `ADDR_CONFIG` 확인 |
| `MISMATCHES`가 크고 첫 오류가 앞쪽 | 가중치 로드 실패. `CFGCOUNT` 먼저 확인 |
| `MISMATCHES`가 크고 첫 오류가 중간부터 | activation 스트림 정렬 문제이거나 timing 미달. WNS 먼저 확인 |
| `IN_STALL`이 큼 | DMA가 못 따라옴. HP 포트 연결과 클럭을 확인. 코어는 4 cycle당 1 word만 요구하므로 정상이면 거의 0이어야 합니다 |

## 범위 밖

전력 측정, 전체 CNN 파이프라인, 여러 레이어 연속 실행, AXI 인터럽트 구동, 리눅스 드라이버는 여기 없습니다.
`CYCLES`는 코어의 스트림 cycle이지 종단간 지연이 아닙니다 — PS 타이머로 찍은 `wall clock`에는 DMA 설정과
캐시 조작이 포함됩니다.

## 부록: DMA가 직전 실행의 데이터를 읽은 건 (2026-09-21)

연속 창 패치를 처음 올렸을 때 131,072개 출력 중 78,541개가 틀렸다. 원인을 데이터로
확정했으므로 기록해 둔다.

증상만 보면 계산이 틀린 것처럼 보였지만, 세 파일(`input.bin`, `config.bin`,
`gold.bin`)은 서로 모순이 없었고, **같은 데이터로 RTL 시뮬레이션은 통과했다**
(iverilog, K=576 COUT=128 P=8 v3, dense 모드, 보드와 같은 조건, cycles 9252.7/window
대 보드 9216.57).

결정적 확인: 보드가 낸 값을 **직전 실행의 `input.bin`**으로 계산한 오라클과 비교했다.

| 비교 대상 | 정확히 일치한 창 |
|---|---|
| 직전 실행의 입력으로 계산한 값 | **1024창 중 832창** |
| 이번에 올린 입력 = `gold.bin` | 123창 |

즉 DMA는 이번에 올린 576 KB 중 대부분을 읽지 못하고 **DDR에 남아 있던 직전 실행의
바이트**를 읽었다. 창 단위 지도에서도 대부분이 예전 데이터고 새 데이터는 드문드문이다.

원인은 Zynq + AXI DMA의 전형적인 캐시 일관성 문제다. `dow -data`는 프로세서의 캐시를
거쳐 쓰고, AXI DMA는 DDR을 직접 읽는다. 데이터가 캐시에 머무르면 가속기는 그 전에
DDR에 있던 것을 본다.

**왜 여태 안 드러났나.** 기존 데이터는 여러 번 반복해서 올렸으므로 DDR이 이미 그
내용으로 수렴해 있었다. 같은 데이터를 다시 올리면 stale이어도 결과가 같다. 처음으로
*다른* 데이터를 올린 순간 드러났다.

**왜 진단이 어려웠나.** `mrd`도 같은 캐시 경로를 읽는다. 쓰기가 들어간 그 캐시를
읽으므로 항상 "정상"으로 보인다. 다운로드 후 읽기 검증을 넣어도 이 문제는 못 잡는다.
서로 다른 `input.bin` 두 개가 보드에서 바이트 단위로 같은 출력을 낸 것이 유일한
단서였다.

미해결: `wm_mmu_off`가 이 보드에서 실패한다(`could not be turned off`). cp15 SCTLR
레지스터 이름이 이 xsdb 버전에서 다른 것으로 보인다. 확인 후 반영할 것.
