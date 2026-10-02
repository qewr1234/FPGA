# UVM 검증 환경 — `window_mac_axis`

보드에서 CIFAR-10 CNN을 돌린 그 IP(`rtl/window_mac_axis.sv` + `banked_window_mac` / `overlapped_window_mac`)를
UVM으로 검증하는 환경입니다. 기존 `sim/tb_axis_wrapper.sv`가 "정해진 벡터 하나를 넣고 결과를 비교"하는
지시형(directed) 테스트벤치라면, 이 환경은 **랜덤 자극 + 참조 모델 + 커버리지 + 프로토콜 assertion** 구조입니다.

## 구조

```
tb_top ── window_mac_axis (DUT)
  │
  ├─ wm_axil_if ── wm_axil_agent  (sequencer / driver / monitor)   ← PS가 레지스터를 쓰고 읽는 쪽
  ├─ wm_axis_if ── wm_axis_agent  (sequencer / driver / monitor)   ← DMA MM2S: 설정·활성값 입력
  └─ wm_axis_if ── wm_axis_agent  (sink / monitor)                 ← DMA S2MM: 결과 출력, TREADY 랜덤
                         │ monitor 3개
                         ▼
                  wm_scoreboard  (참조 모델)  ──►  wm_coverage (covergroup)
```

| 파일 | 내용 |
|---|---|
| `wm_if.sv` | AXI4-Lite / AXI4-Stream 인터페이스. "VALID가 올라가면 READY까지 유지, 데이터 고정" 규칙을 SVA로 검사 (DUT 쪽과 벤치 쪽 모두) |
| `wm_axil_agent.svh` | 레지스터 접근 1회 = item 1개 |
| `wm_axis_agent.svh` | 패킷(=DMA 전송 1회) 단위 드라이버, beat 단위 모니터, 출력 싱크 |
| `wm_scoreboard.svh` | **참조 모델.** 시퀀스가 무엇을 보냈는지는 모르고, 모니터가 버스에서 본 것만으로 결과를 예측 |
| `wm_coverage.svh` | 실행 1회마다 샘플: K/COUT 경계, dense/sparse/교대, 0 활성값·전부 0인 윈도우, ReLU, INT8 극값, 스로틀 |
| `wm_seqs.svh` | `wm_layer`(랜덤 레이어 기술) + 보드 드라이버와 같은 순서로 레이어 1개를 돌리는 `wm_layer_vseq` |
| `wm_tests.svh` | 테스트 4종 (아래) |
| `tb_top.sv` | 클럭·리셋·DUT·config_db. DUT 파라미터는 런너가 빌드마다 바꿈 |

### 스코어보드가 검사하는 것

- **모든 출력 값과 순서**: `ReLU(bias[c] + Σ w[c][t]·a[t])`. 윈도우 순, 채널 순입니다. TLAST는 마지막 윈도우의 마지막 채널에서만 나와야 합니다.
- **레지스터**: ID, RUN_K/RUN_COUT(0이나 빌드보다 큰 값은 빌드 크기로 clamp), CTRL 되읽기, NWINDOWS, CFGCOUNT, 실행이 끝난 뒤의 WINDONE/OUTCOUNT, 매핑되지 않은 주소(0).
- **STATUS.done**: 예측한 출력을 전부 받기 전에 done이 뜨면 에러입니다.
- **CYCLES**: 입력 포트는 사이클당 활성값을 1개 받으므로, 실행은 `NWINDOWS × K` 사이클보다 짧을 수 없습니다(하한 검사). 정확한 사이클 수는 기존 `scripts/run_axis_checks.py`가 사이클 모델과 비교합니다.
- **IN_STALL / OUT_STALL**: 아무것도 스로틀하지 않은 실행에서는 0이어야 합니다.
- **무시해야 하는 비트**: 랜덤 테스트는 가중치 beat의 [31:8]과 활성값 바이트의 bit 7에 쓰레기 값을 넣습니다. DUT가 이 값을 무시해야 결과가 맞습니다.

### 테스트

| 테스트 | 내용 |
|---|---|
| `wm_smoke_test` | 빌드 최대 형상, dense, 스로틀 없음, 레이어 1개 |
| `wm_reg_test` | 리셋 값 → 레지스터 쓰기/읽기·clamp·읽기전용·미매핑 주소 → 그 뒤에도 연산이 맞는지 레이어 1개 |
| `wm_random_test` | `+WM_LAYERS=N`개 레이어를 리셋 없이 연속 실행. 형상·모드·데이터·입출력 스로틀·쓰레기 비트를 모두 랜덤으로 |
| `wm_cifar_shapes_test` | CIFAR 6개 conv 층의 실제 K·COUT·측정 밀도를 **보드 비트스트림과 같은 빌드**(K=1152, COUT=128, P=16, T=4)에서 |

### 빌드 (`scripts/run_uvm.py`의 `BUILDS`)

| 이름 | K | COUT | P | T | IMPL | RUNTIME_GEOM |
|---|---|---|---|---|---|---|
| small | 48 | 20 | 4 | 4 | 3 (v4, 보드 코어) | 1 |
| v3 | 48 | 20 | 4 | – | 2 (v3) | 1 |
| fixed | 24 | 9 | 2 | 2 | 3 | 0 (고정 형상) |
| board | 1152 | 128 | 16 | 4 | 3 | 1 ← CIFAR를 돌린 비트스트림과 동일 |

## 실행

### Windows + Vivado (xsim)

Vivado에는 UVM 1.2가 미리 컴파일되어 들어 있어서 따로 설치할 것이 없습니다.

```
cd C:\fpga\FPGA
git pull
python scripts\run_uvm.py --sim xsim
```

Vivado를 못 찾으면 `--vivado-bin C:\Vivado\2026.1\Vivado\bin`처럼 bin 폴더를 직접 주세요. 하나만 빠르게 보려면 이렇게 합니다.

```
python scripts\run_uvm.py --sim xsim --build small --test wm_smoke_test --seeds 1
```

결과는 `build\uvm\xsim\summary.json`과 테스트·시드별 로그에 남습니다.

### Linux + Verilator

Verilator 5.040 이상, z3, Accellera UVM 소스가 필요합니다.

```
python3 scripts/run_uvm.py --sim verilator --uvm-home <uvm-1.2 경로>
python3 scripts/run_uvm.py --sim verilator --uvm-home <uvm-1.2 경로> --mutants
```

## 검증 결과 (Verilator 5.052)

결과 표와 뮤턴트 표는 `RESULTS_UVM_KO.md`에 있습니다(`run_uvm.py --report`가 생성).

**뮤턴트 검사**는 RTL 사본에 알려진 버그를 하나씩 심고, 테스트가 그것을 FAIL로 잡는지 확인합니다. "통과"가 아무것도 검사하지 않아서 나온 통과가 아니라는 근거입니다.
- 첫 실행에서 1개가 살아남았습니다(래퍼가 가중치를 부호 확장하지 않게 만든 버그).
- 원인을 보니 두 코어 모두 `cfg_data[7:0]`만 저장하기 때문에, 그 부호 확장은 원래 결과에 영향이 없는 코드였습니다. 즉 **등가 뮤턴트**였습니다.
- 그래서 실제로 동작이 바뀌는 버그(코어가 가중치의 부호 비트를 잃음)로 바꿨습니다. 그 경위는 `scripts/run_uvm.py`의 `MUTANTS` 주석에 남겼습니다.

## 한계 — 솔직하게

- **xsim에서는 아직 한 번도 돌려보지 않았습니다.** 이 컨테이너에는 Vivado가 없습니다. 명령줄(`xvlog -sv -L uvm`, `xelab -L uvm`, `xsim -runall -testplusarg`)은 UG900과 공개 예제로 확인했지만, xsim 문법 차이로 첫 실행에서 컴파일 에러가 날 수 있습니다. 나면 로그를 보내 주세요.
- 실행 도중 RUN_K/RUN_COUT/NWINDOWS를 바꾸는 경우, 실행 중 코어 리셋(CTRL[0]), NWINDOWS=0은 모델링하지 않습니다. 실행 중 형상 레지스터를 쓰면 스코어보드가 에러를 냅니다.
- DUT는 AXI-Lite WSTRB를 무시합니다(항상 32비트 전체 쓰기). PS의 32비트 쓰기만 쓰는 지금 용도에서는 문제없지만, 바이트 단위 쓰기를 쓰면 AXI 규격과 다르게 동작합니다. 벤치도 WSTRB=1111만 씁니다.
- 레지스터 모델은 UVM RAL이 아니라 스코어보드 안의 간단한 미러입니다. RAL은 다음 단계입니다.
- Verilator에서 발견한 차이 3가지를 코드 주석에 남겼습니다.
  - `dist` 구간을 먼저 뽑는 방식이라, 인라인 제약과 겹치면 randomize가 실패합니다. 그래서 dist 블록을 끄고 값을 고정합니다.
  - 가상 인터페이스에 `?:`를 쓸 수 없습니다.
  - 커버포인트 단위로 `get_inst_coverage()`를 부를 수 없습니다. 그래서 커버그룹을 주제별로 나눴습니다.
