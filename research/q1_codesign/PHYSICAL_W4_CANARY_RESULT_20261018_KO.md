# Q1 FPGA W4 Original 단독 재검증 — 실제 보드 Canary 결과

날짜: 2026-10-18. 근거: 사용자 업로드 canary.json, report(1).json. 실제 FPGA Original 단독 결과이며 **3종 모델 간 성능 비교는 아님**.

## 측정 결과

- Canary 상태: PHYSICAL_ORIGINAL_W4_CANARY_PASS
- 모델: dn_d10_c32_us_fx_qat; Set12 05.png; sigma25; noise seed0; W4 sparse mode=1.
- 실제 FPGA 10개 Conv 레이어: 13,289,030 cycles at 50 MHz.
- 코어 ID: 0x4d410303. 10개 Conv 전체 bit-exact oracle 불일치 0.
- 과거 GitHub 실제 FPGA 원본: 13,289,042 cycles. 이번과 차이는 -12 cycles.
- 과거 DMA IN_STALL 12, 이번 IN_STALL 0; 양쪽 OUT_STALL 0.
- 이전 Conv5만 1,562,948 → 1,562,936 cycles이며, 나머지 9개 Conv는 정확히 일치.
- 이번 PL core cycles의 시간 환산 265.7806ms (end-to-end latency 아님).
- Conv2–9 합계: 11,421,202 cycles.

## 레이어별 하드웨어 사이클

| Layer | Earlier cycles | Canary cycles | Canary IN_STALL |
|---|---:|---:|---:|
| Conv1 | 524,305 | 524,305 | 0 |
| Conv2 | 1,504,752 | 1,504,752 | 0 |
| Conv3 | 1,435,005 | 1,435,005 | 0 |
| Conv4 | 1,448,350 | 1,448,350 | 0 |
| Conv5 | 1,562,948 | 1,562,936 | 0 |
| Conv6 | 1,369,221 | 1,369,221 | 0 |
| Conv7 | 1,375,441 | 1,375,441 | 0 |
| Conv8 | 1,289,021 | 1,289,021 | 0 |
| Conv9 | 1,436,476 | 1,436,476 | 0 |
| Conv10 | 1,343,523 | 1,343,523 | 0 |
| **Total** | **13,289,042** | **13,289,030** | **0** |

## Current actual programmed build

Build path: C:\fpga\FPGA\build\zed_v4_p16_t4_w4_1792234898
Bitstream SHA256: 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6
Project BoardPart xilinx.com:zc702:part0:1.4. Past report has no .bit hash, so historical/current byte identity remains unproven; however, **this current SHA-bound bitstream has now passed an actual W4 Original physical test**. The test does not certify manufacturer board PS presets.

## Next research gate

Same physical board confirmed by user, same bitstream, 3 reps alternating Original/Frozen/Multi-start, 10 layer bitwise oracle, separate Conv2–9 and Conv1–10 cycles, DMA IN/OUT stalls.

Windows FPGA PC command (after checking identical board, wiring and XSDB):

    cd /d C:\fpga\FPGA
    git pull origin main
    RUN_FPGA_Q1_TRIPLET_EXISTING_W4.cmd "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" canary_01 trial_01

The runner requires explicit SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED acknowledgement and physical canary SHA match. This is a physical programming command; no automatic board certification implied.

Existing Canary:
- C:\fpga\FPGA\build\q1_existing_w4_canary\canary_01\canary.json
- C:\fpga\FPGA\build\q1_existing_w4_canary\canary_01\original\report.json

Future 3-way physical results (not yet created):
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.md

## Claim limitation

No Frozen/Multi-start actual FPGA speedup measured yet. The prior 10.708853% Conv2–9 modeled reduction from BSD68 is NOT hardware measurement. Actual board comparison must establish positive speedup or report failure, and must not extrapolate end-to-end latency or energy improvements.
