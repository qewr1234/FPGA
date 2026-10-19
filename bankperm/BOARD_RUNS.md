# Board runs of the layout study: what to run, what is predicted

All runs use the existing W = 4 bitstream (the earlier canary's SHA-256, 11641ab3…),
`--w4 --mode 1 --fclk 50`, network B-32 ReLU + QAT s1 (`dn_d10_c32_us_fx_qat`), Set12 05–08.png.
Each prediction (exact per-layer cycles: count + the `w4_gaps.py` fill-and-drain rule,
conv1's measured 17) was committed before its runs and reviewed by an independent script
that recomputed every layer of the runs it checked without importing the predictor. A
layer is predicted if CYCLES − IN_STALL equals its value exactly.

| Step | Script | Prediction (committed) | Runs | Status |
|---|---|---|---|---|
| 0 | `RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd` | — | copies the raw reports of the earlier canary and triplet runs from `build\` | to do |
| 1 | `RUN_W4_LAYOUTS.cmd` | `board_prediction_2.json` (7312a84; PROTOCOL_2) | Original, Frozen, Multi-start, Skew × 05–08 (16 runs, ~2.5 h) | to do |
| 2 | `RUN_W4_L3.cmd` (needs step 1 finished) | `board_prediction_3.json` (0887924, reviewed; unchanged since; PROTOCOL_2_ADDENDUM) | skew + relabeling (L3) × 05–08 (4 runs, ~40 min) | to do |

The WIP commit 0887924 that first holds `board_prediction_3.json` said "not reviewed": the
review finished afterwards and changed nothing in that file (its git blob is the same at
68c3088, where the L3 tooling is final). Both run scripts refuse to start if their
prediction differs from the committed one, if an export file or a pinned tool differs from
its recorded hash, or if the bitstream is not the canary's.

## Predicted totals (cycles, conv1–conv10)

| Layout | 05.png | 06.png | 07.png | 08.png |
|---|---|---|---|---|
| Original | 13,289,030 | 13,465,669 | 13,412,001 | 51,976,969 |
| Frozen | 12,355,814 | 12,400,408 | 12,443,401 | 48,895,091 |
| Multi-start | 12,278,419 | 12,251,825 | 12,354,312 | 48,555,823 |
| Skew (L2) | 12,140,286 | 12,123,612 | 12,211,336 | 48,176,562 |
| Skew + relabeling (L3) | 12,041,720 | 12,028,030 | 12,119,810 | 47,847,154 |

On 05.png the Original, Frozen and Multi-start values equal the earlier board runs
(transcribed: 49 comparisons; raw report: 11 comparisons; all exact). Set12 06–08, the
skew and L3 have never run on the board.

## On the board PC (C:\fpga\FPGA)

```
git checkout claude/determined-keller-qurd64
git pull origin claude/determined-keller-qurd64
RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd
RUN_W4_LAYOUTS.cmd C:/Vivado/2026.1/Vivado/bin/xsdb.bat
git pull origin claude/determined-keller-qurd64
RUN_W4_L3.cmd C:/Vivado/2026.1/Vivado/bin/xsdb.bat
```

Each run script prints, at the end, the `git add / commit / push` lines for its results.
