# Existing W4 FPGA: history → physical Original-only canary → 3-way A/B/C

Date 2026-10-18.

## Validated physical history

Source: uploaded audit.json / audit.md, independently matching denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json.

- Model: dn_d10_c32_us_fx_qat, Set12 05.png, sigma25, W4 sparse mode=1.
- 10 Conv layers; physical core ID 0x4d410303; FCLK 50MHz; output mismatches 0.
- Previous physical cycles: **13,289,042**. IN_STALL=12, OUT_STALL=0. W1-to-W4: 3.296807x.
- Local W4 candidate: C:\fpga\FPGA\build\zed_v4_p16_t4_w4_1792234898\system_wrapper.bit.
- Candidate .bit SHA256: 11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6.

**The historical W4 report lacks original bitstream SHA.** Thus no claim of proven byte-identical historical/current .bit. But past actual W4 hardware success is proven.

The original audit tool's Vivado BD extraction erroneously showed { for several PS settings. This parsing bug is fixed in GitHub with nested JSON lookup and a regression test. Correct source values: FCLK setting 100, DDR part MT41J256M8 HX-15E, DDR frequency 533.333333, address high 0x3FFFFFFF. Runtime prior hardware clock was recorded at 50MHz; the design's PS preset is ZC702. Those are separate facts.

## Controlled progress without automatically approving unknown board

The old triplet script blocked zed_v folder naming outright. The updated triplet script permits an older build ONLY after an original-only **physical canary** on that exact bitstream and SHA256.

The same board that previously ran W4 must be physically confirmed by its operator. BoardPart alone is not proof of Smart ZYNQ SL DDR/MIO compatibility. No tool can remotely certify that the board currently attached is the former physical board. If unknown or changed, STOP before physical programming.

### Step 1. Original-only physical canary

On the PC with the SAME previously working board and verified power/DDR/MIO setup:

    cd /d C:\fpga\FPGA
    git pull origin main
    RUN_FPGA_Q1_W4_CANARY.cmd "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" canary_01

Replace XSDB path if your actual installation differs. The script first runs read-only prechecks. It asks for explicit human approval before programming. Type SAME_PHYSICAL_BOARD_PREVIOUSLY_RAN_W4 only if true.

The live run must pass: identical SHA to local provenance audit, actual core ID 0x4d410303, 50MHz, all 10 layer integer mismatch counts zero, Set12 05.png sigma25, original core total within 2% of historical 13,289,042. A 2% threshold is a safety/sanity guard, not an acceleration metric.

**File to upload after step 1:**

C:\fpga\FPGA\build\q1_existing_w4_canary\canary_01\canary.json

Additional physical raw board file:

C:\fpga\FPGA\build\q1_existing_w4_canary\canary_01\original\report.json

If the canary doesn't PASS, STOP. No A/B/C.

### Step 2. Original / Frozen / Multi-start A/B/C

Only after passed physical canary, same hardware and a further affirmative manual board-verified check:

    RUN_FPGA_Q1_TRIPLET_EXISTING_W4.cmd "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" canary_01 trial_01

It executes three alternating-order repetitions, using the identical bitstream, and validates each image/layer.

**Files to upload after step 2:**

C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json

C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.md

Raw logs live in C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\rep_01\ etc.

## Scientific scope

The old GPU reduction 10.708853% is an analytical Conv2–9 result on BSD68 sigma15/25/50. These FPGA triplet runs will measure all ten layers on Set12 05.png, so do not directly equate percentages. Separate core cycles, Conv2–9 versus all layers, recorded DMA stalls, PS latency, and end-to-end wall time. Do not claim power improvement.

## Passing offline CI tests

- Provenance and Vivado PS nested-JSON tests: https://github.com/qewr1234/FPGA/actions/runs/39111127679
- Triplet model-export integrity preflight: https://github.com/qewr1234/FPGA/actions/runs/39111328697
- Canary physical-result tampering / exact-bit SHA gating: https://github.com/qewr1234/FPGA/actions/runs/39111420987

All CI checks were offline and did not program any FPGA.
