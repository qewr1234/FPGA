# UVM 검증 결과

`python scripts/run_uvm.py --report`가 `build/uvm/*/summary.json`에서 생성했습니다. 손으로 옮겨 적은 숫자는 없습니다.

Verilator: `Verilator 5.052 2026-09-05 rev v5.052`

## verilator_1800.2-2020.3.1  —  UVM: `1800.2-2020.3.1`

**26/26 통과**, 출력 23,043개, 레지스터 읽기 4,774개 비교.

| 빌드 | 테스트 | 시드 | 결과 | 비교한 출력 | 레지스터 읽기 | 커버리지 (형상 / 모드×0 / 데이터 / 흐름) |
|---|---|---|---|---|---|---|
| small | wm_random_test | 1,2 | 2/2 | 8,435 | 1,743 | 91–100% / 100% / 100% / 100% |
| small | wm_reg_test | 1,2 | 2/2 | 46 | 160 | 9% / 20% / 33% / 38% |
| small | wm_smoke_test | 1,2 | 2/2 | 80 | 14 | 9% / 20% / 67% / 38% |
| v3 | wm_random_test | 1,2 | 2/2 | 8,435 | 1,743 | 74–83% / 100% / 100% / 100% |
| v3 | wm_reg_test | 1,2 | 2/2 | 46 | 160 | 9% / 20% / 33% / 38% |
| v3 | wm_smoke_test | 1,2 | 2/2 | 80 | 14 | 9% / 20% / 67% / 38% |
| fixed | wm_random_test | 1,2 | 2/2 | 1,944 | 461 | 9% / 100% / 100% / 100% |
| fixed | wm_reg_test | 1,2 | 2/2 | 36 | 160 | 9% / 20% / 33–50% / 38% |
| fixed | wm_smoke_test | 1,2 | 2/2 | 36 | 14 | 9% / 20% / 50–67% / 38% |
| board | wm_cifar_shapes_test | 1,2 | 2/2 | 1,792 | 84 | 26% / 20–33% / 67% / 38% |
| board | wm_random_test | 1,2 | 2/2 | 1,467 | 47 | 17–26% / 47–60% / 83% / 62–88% |
| board | wm_reg_test | 1,2 | 2/2 | 134 | 160 | 9% / 20% / 33–67% / 38% |
| board | wm_smoke_test | 1,2 | 2/2 | 512 | 14 | 9% / 20% / 67% / 38% |

## verilator_uvm-1.2  —  UVM: `uvm-1.2`

**39/39 통과**, 출력 38,809개, 레지스터 읽기 7,114개 비교.

| 빌드 | 테스트 | 시드 | 결과 | 비교한 출력 | 레지스터 읽기 | 커버리지 (형상 / 모드×0 / 데이터 / 흐름) |
|---|---|---|---|---|---|---|
| small | wm_random_test | 1,2,3 | 3/3 | 14,237 | 2,590 | 89–97% / 100% / 100% / 100% |
| small | wm_reg_test | 1,2,3 | 3/3 | 82 | 240 | 9% / 20% / 33–67% / 38% |
| small | wm_smoke_test | 1,2,3 | 3/3 | 120 | 21 | 9% / 20% / 67% / 38% |
| v3 | wm_random_test | 1,2,3 | 3/3 | 14,237 | 2,590 | 74–83% / 100% / 100% / 100% |
| v3 | wm_reg_test | 1,2,3 | 3/3 | 82 | 240 | 9% / 20% / 33–67% / 38% |
| v3 | wm_smoke_test | 1,2,3 | 3/3 | 120 | 21 | 9% / 20% / 67% / 38% |
| fixed | wm_random_test | 1,2,3 | 3/3 | 3,204 | 693 | 9% / 93–100% / 100% / 100% |
| fixed | wm_reg_test | 1,2,3 | 3/3 | 54 | 240 | 9% / 20% / 50% / 38% |
| fixed | wm_smoke_test | 1,2,3 | 3/3 | 54 | 21 | 9% / 20% / 50–67% / 38% |
| board | wm_cifar_shapes_test | 1,2,3 | 3/3 | 2,688 | 126 | 26% / 20% / 67% / 38% |
| board | wm_random_test | 1,2,3 | 3/3 | 2,649 | 71 | 20–29% / 60–67% / 83–100% / 88–100% |
| board | wm_reg_test | 1,2,3 | 3/3 | 514 | 240 | 9% / 20% / 50–67% / 38% |
| board | wm_smoke_test | 1,2,3 | 3/3 | 768 | 21 | 9% / 20% / 67% / 38% |

### 커버리지 읽는 법

- 커버리지는 시뮬레이션 1회 안에서 계산합니다. 시드끼리 합치지 않습니다. 표는 시드별 값의 최소–최대입니다.
- smoke / reg / cifar_shapes는 정해진 레이어 몇 개만 돌리므로 낮은 것이 정상입니다. 랜덤 테스트의 숫자가 의미 있는 값입니다.
- **fixed** 빌드는 형상이 고정(K=24, COUT=9)이라 형상 칸 25개 중 1개 조합만 존재합니다. 9%가 최대입니다.
- **v3**는 bank가 없어서(T=1) "K가 bank 수의 배수가 아님" 칸에 도달할 수 없습니다. 형상 최대가 100%가 아닙니다.
- **board**의 랜덤 테스트는 레이어가 크기 때문에(K≤1152) 4개만 돌립니다. 형상 칸을 채우는 역할은 small 빌드가 맡습니다.

## 뮤턴트 (일부러 심은 버그)

**10/10 검출.** small 빌드에서 smoke / reg / random(12 레이어) × 시드 2개를 돌려, 하나라도 FAIL이면 "검출"입니다.

| 뮤턴트 | 깨지는 것 | 결과 | 잡은 테스트 |
|---|---|---|---|
| `relu_removed` | negative sums are emitted instead of clamped to 0 | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `weight_sign_lost` | negative INT8 weights are stored as positive | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `lane1_reads_lane2` | the second activation of every beat is the third | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `tlast_every_window` | TLAST on the last channel of every window | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `walker_ignores_run_k` | configuration walked at the built K, not RUN_K | 검출 | wm_random_test, wm_reg_test |
| `run_k_clamp_off_by_one` | RUN_K accepts K+1 | 검출 | wm_reg_test |
| `done_one_window_early` | the run ends, and TLAST comes, one window early | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `in_stall_counts_idle` | IN_STALL counts cycles the core did not want input | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `last_bias_dropped` | the last channel keeps the previous layer's bias | 검출 | wm_random_test, wm_reg_test, wm_smoke_test |
| `sparse_drops_ones` | sparse mode skips activations equal to 1 as if they were 0 | 검출 | wm_random_test |
