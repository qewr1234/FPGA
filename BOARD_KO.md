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
| PS 애플리케이션 (`sw/window_mac_test.c`) | 문법 검사만 — **보드에서 미실행** |
| Vivado 빌드 (`scripts/build_zedboard.tcl`) | **실행됨** — xc7z020clg484, v3 P=8 @100MHz, WNS +0.919 ns, 0 errors |
| 보드 로드 (`scripts/run_board.tcl`) | 미실행 — 보드 없음 |

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

Vitis에서 `system_wrapper.xsa`로 플랫폼을 만들고, 빈 C 애플리케이션의 `main.c`를
`sw/window_mac_test.c` 내용으로 교체해 빌드하면 `window_mac_test.elf`가 나옵니다.

그 다음 Vitis 디버거 셸 — 예전 설치는 `xsct`, 2024.2 이후는 `xsdb`, 명령은 같습니다 — 에서:

```tcl
cd C:/fpga/FPGA
source scripts/run_board.tcl
```

비트스트림·XSA·데이터·ELF를 찾아서 순서대로 올리고 실행합니다. `build/zed_*` 중 가장 최근 것을
쓰고, 데이터 크기를 확인하고, DDR에 한 워드를 써봤다 읽어 PS 프리셋이 이 보드에 맞는지 먼저
확인합니다. 뭔가 빠지면 그 자리에서 멈추고 무엇이 없는지 말합니다.

다른 빌드나 다른 위치의 ELF를 쓰려면:

```tcl
set ::env(WM_BUILD) C:/fpga/FPGA/build/zed_v3_p8_t4_1789907417
set ::env(WM_ELF)   C:/vitis_ws/window_mac_test/build/window_mac_test.elf
```

직접 치실 거면 스크립트가 하는 일은 이겁니다:

```tcl
connect
targets -set -filter {name =~ "ARM*#0"}
fpga -file system_wrapper.bit
loadhw -hw system_wrapper.xsa -mem-ranges [list {0x40000000 0xbfffffff}]
ps7_init; ps7_post_config
dow -data config.bin 0x10000000
dow -data input.bin  0x10100000
dow -data gold.bin   0x10300000
dow window_mac_test.elf
con
```

UART(115200)로 결과가 나옵니다.

## 결과 읽는 법

```
MISMATCHES     : 0
CYCLES         : 7404123
  per window   : 7230.58
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
