# bankperm: tap-to-bank layouts for the banked W = 4 core

This folder holds the evidence and the manuscript for one question: when does the
layout of a window's taps over the lockstep banks pay? On the banked window-MAC
core (P = 16 output lanes, T = 4 banks, slot j of a window in bank j % 4, sparse
mode), each window waits for the bank with the most nonzero taps, so the slot
the host gives each tap sets the cycles. Four layouts, all leaving the bitstream
and the integer output unchanged (`PROTOCOL_2.md`):

- **L0**, conventional (the Original): tap s·C + p in slot s·C + p, bank p % 4 when 4 divides C;
- **L1**, channel relabeling: hidden channels permuted, fitted offline on calibration images and folded into the producer's filters, bias and requantization and the consumer's weights (the board's Frozen and Multi-start);
- **L2**, skew: channel p of 3×3 position s in slot s·C + (p + s) % C, bank (p + s) % 4, applied by the host to the windows and the weight columns (no fit, no RTL change);
- **L3**, skew + relabeling: L1's recipe refitted under the skewed bank rule, then skewed.

The folder records:

- where no layout can change the cycles, from the layer shapes alone (`bounds.py`);
- the board run of L0 and the two relabelings of B-32 ReLU + QAT s1 (`dn_d10_c32_us_fx_qat`) on Set12 05.png at W = 4, and the exact prediction of every measured number (`b32_board.py`);
- their counts on all 80 test images (`b32_testsets.py`);
- the first pre-registered study, L1 on all ten networks of `denoise/count_test_sets.py` (`PROTOCOL.md`, `fit.py`, `fold.py`, `evaluate.py`; H0–H3);
- baselines on the board network (`baselines.py`) and the first count of the skew (`skew_count.py`, after that study);
- the second pre-registered study, L2 and L3 against L0 and L1 on all ten networks with bootstrap intervals (`PROTOCOL_2.md`, `evaluate_2.py`, `DEVIATIONS_2.md`; H4–H6), and bootstrap intervals for the board network's baselines (`stats_2.py`);
- the skew's host path and its check (`export_layout.py`, `check_skew_export.py`), the host time per image (`host_time.py`), and the exact predictions of the PROTOCOL_2 board runs, committed before them (`predict_board_2.py`, `board_prediction_2.json`; the runs are under way, `RUN_W4_LAYOUTS.cmd`); `PROTOCOL_2_ADDENDUM.md` adds board runs of L3;
- the paper's three figures (`figures/`, drawn from the JSON files of this folder);
- the related work (`references.json`, `RELATED_WORK_EN.md`), the paper (`PAPER_EN.md`, built into the IWEICT Word template; its title and abstract are those of the submission form, `ABSTRACT_IWEICT.md`) and a short insert for the IWEICT paper (`IWEICT_INSERT_EN.md`).

## Measured, counted, transcribed

| Kind | What | Where |
|---|---|---|
| Measured on the board, committed raw report | the earlier W = 4 run of the Original export of the board network on Set12 05.png (13,289,042 cycles, 12 of them IN_STALL in conv5; 315.0 s of JTAG debugger time over its ten layers) | `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json`, `denoise/w4_measured.json` |
| Measured on the board, **transcribed** | the canary run of the Original and three repeats of Original, Frozen and Multi-start (2026-10-18) | `board_transcribed.json`: every value with file, line and the exact quote from `research/q1_codesign/PHYSICAL_W4_*_20261018_KO.md`. The raw `report.json` files, XSDB logs and PNG digests are **not in the repository** (`denoise/board_runs/q1_layouts/`, which `RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd` would create, did not exist locally or on GitHub on 2026-10-19 when the paper was rebuilt); Frozen's per-layer board cycles were never given, only its total and its conv2–9 sum |
| Predicted exactly | per-window count + per-layer fill and drain (`denoise/w4_gaps.py`; conv1 a measured constant, 17) | `b32_board.json` `layouts.*.layers[].exact_w4`, compared in `board_vs_prediction`. Its `status` "out of sample" is by layout: Multi-start conv10 and the totals are labelled out of sample although conv1 and conv10 see the same windows in every layout (only conv1–conv8 outputs are permuted, `sources.*.permuted_outputs`), so of its 21 out-of-sample comparisons nine are independent (Multi-start conv2–conv9, Frozen conv2–9 sum) |
| Predicted, **not yet run** | every layer of L0, Frozen, Multi-start and L2 on Set12 05–08 (PROTOCOL_2's board runs; 06–08 and the skew never ran on the board) | `board_prediction_2.json` (7312a84, before the runs). The paper only says these runs are pre-registered and under way |
| Counted | per-window count of `denoise/predict_w4.window_cycles` (sparse mode) over the windows of the host emulation (`scripts/run_denoise.py`), fill and drain left out | everything else: `b32_testsets.json`, `results.json`, `results_2.json`, `baselines.json`, `skew_count.json`, the counts in `b32_board.json`; intervals: `results_2.json`, `stats_2.json` |
| Timed on the x86 server, not on the board | host work per image (input, im2col, requantization) of the board network on 05.png | `host_time.json` (single-threaded medians of 5 runs; core time = exact board cycles at 50 MHz; transfer time not counted) |
| From layer shapes only | where a layout can pay | `bounds.json` |

All counts are at σ = 25 with one noise draw per image (`test_noise` seed 0).
W = 2 numbers are counts only; no W = 2 board run exists. An independent
verification of `results_2.json`, `stats_2.json` and `host_time.json` may still be
running; if it reports a mismatch, the paper and this map are corrected then.

## Pre-registration (UTC)

Times are from `git log`; GitHub's push records of the public repository
(`gh api repos/qewr1234/FPGA/activity` for the branch, `.../events` for `main`)
match them within seconds, so the order does not rest on author-set dates alone.
The paper calls them push times.

| When | Commit | What was fixed |
|---|---|---|
| 2026-10-17 07:52 | 7e81f6b | W = 4 per-window count model (`denoise/predict_w4.py`), before the W = 4 bitstream existed |
| 2026-10-17 12:07 | 0e6075d | first W = 4 board runs of the four original networks (incl. the board network's Original) |
| 2026-10-17 13:15 | 6dc0e60 | fill-and-drain rule (`denoise/w4_gaps.py`), read off those runs: Original layers are in sample |
| 2026-10-17 15:49 | b37f971 | drain constant written as 3 + channels in the last 16-lane group (19 at COUT 32, unchanged here); IN_STALL counter fixed in RTL, not in the W = 4 bitstream that ran |
| 2026-10-17 18:38 | 9cf9c79 | Frozen per-layer count savings (%) and the conv2–9 count 10,487,498 on 05.png (`research/q1_codesign/BANK_PRELIM_RESULTS_20261018_KO.md` l. 13 and 19), before the board run; not per-layer cycle counts |
| 2026-10-17 19:25 / 21:00 | c2ad6ad / 45b4f16 | Frozen and Multi-start export ZIPs |
| 2026-10-18 | — | canary and triplet board runs (documents committed 09:16–12:20 UTC; the trial audit with the 89 PASS + 1 DMA-bound and 90-layer lines is 5e6116b, 12:20) |
| 2026-10-18 18:32 | c2299e2 | `PROTOCOL.md`, `bounds.py`, `bounds.json`: recipe, evaluation and predictions H0–H3, before any fit on the other nine networks |
| 2026-10-18 19:29 | b3461cf | `fit.py`, `perms.json`, `fold.py`, `fold_check.json`, `evaluate.py`, `DEVIATIONS.md`, `b32_*`, `baselines.*`, `board_transcribed.json`, before `results.json` was written (the complete evaluation run was still going when this was pushed; a re-run of the committed `evaluate.py` reproduced `results.json` for B-32 ReLU s1 and 10 × 45) |
| 2026-10-19 03:54 | 2928d28 | `skew_count.py`, `skew_count.json`: L2 counted on the board network (80 images) and on 05.png of A, B, maxout s1 and 10 × 45, after the first study and outside it |
| 2026-10-19 06:07 | 951c8f1 | `PROTOCOL_2.md`: L0–L3, the paired bootstrap, H4–H6 and the board runs, before any L2/L3 count beyond 2928d28's and before the L3 fit; it discloses what was seen before it (2928d28 and uncommitted review counts: L2 on 8 images each of B and maxout s1, L3 on 7 images of the board network) |
| 2026-10-19 06:18–07:19 | — | the PROTOCOL_2 run (`evaluate_2.py`, one invocation; `DEVIATIONS_2.md` 7–8) |
| 2026-10-19 07:12 | ce19450 | `evaluate_2.py`, `perms_2.json` (the L3 fit), `stats_2.json`, `host_time.json`, the skew's host path (work in progress) |
| 2026-10-19 07:21 | 7312a84 | `board_prediction_2.json`: exact per-layer cycles of the PROTOCOL_2 board runs (L0, Frozen, Multi-start, L2 on Set12 05–08), before the runs; `skew_export_check.json` |
| 2026-10-19 07:22 | 4a93e08 | `results_2.json`, `DEVIATIONS_2.md`: H4–H6 hold |
| 2026-10-19 07:23 | d6521ec | `PROTOCOL_2_ADDENDUM.md` (L3 board runs; its prediction to be committed before them) and the form abstract `ABSTRACT_IWEICT.md` |
| 2026-10-19 07:38 | 0887924 | work in progress, not reviewed: L3 board tooling and `board_prediction_3.json` (not used by the paper), and Fig. 2 and 3 redrawn |

`PROTOCOL.md`, `PROTOCOL_2.md`, `bounds.py` and `bounds.json` must not be edited. The one place where
the first protocol could not be applied word for word (the 45-channel network) is in
`DEVIATIONS.md`; the readings PROTOCOL_2 needed are in `DEVIATIONS_2.md`.

## Reproducing every number

Prerequisites: the repository's exports (`denoise/export/<model>/`), the two ZIPs
in `research/q1_codesign/artifacts/`, the test images (`python denoise/get_data.py`),
python3 with numpy. Run from the repository root, in this order. Times: 4-core x86
machine, 2 worker processes; where a JSON stores its own time it is named, the
others are from the run logs of 2026-10-18.

| Step | Command | Writes | Time |
|---|---|---|---|
| 1 | `python3 bankperm/bounds.py` | `bounds.json` (pre-registered; do not commit a changed one) | not timed |
| 2 | `python3 bankperm/b32_board.py` | `b32_board.json` (reads `board_transcribed.json` and checks every citation) | 14 s (log) |
| 3 | `python3 bankperm/b32_testsets.py --jobs 2` | `b32_testsets.json` | 712 s (log) |
| 4 | `python3 bankperm/fit.py` | `perms.json` | 126.6 s (`perms.json` `networks.*.seconds`, summed) |
| 5 | `python3 bankperm/fold.py --cli --jobs 2` | `fold_check.json` | 303 s wall (log; 562.9 s summed over networks in `fold_check.json`) |
| 6 | `python3 bankperm/evaluate.py --jobs 2` | `results.json` | 4,659 s wall (`results.json` `wall_seconds`) |
| 7 | `python3 bankperm/baselines.py --jobs 2` | `baselines.json` (imports `fit.py` and `b32_board.py`; compares with `b32_testsets.json` if present) | 628 s (`baselines.json` `seconds`) |
| 8 | `python3 bankperm/skew_count.py --jobs 2` | `skew_count.json` | not stored |
| 9 | `python3 bankperm/evaluate_2.py --cache DIR --jobs 2` | `perms_2.json` (L3 fit), then `results_2.json` | 3,680 s wall (`results_2.json` `runtimes.runs[0].wall_seconds`) |
| 10 | `python3 bankperm/stats_2.py` | `stats_2.json` | 0.2 s (`seconds`) |
| 11 | `python3 bankperm/host_time.py` | `host_time.json` | 22.4 s (`seconds`) |
| 12 | `python3 bankperm/check_skew_export.py` | `skew_export_check.json` | 275 s (`seconds`) |
| 13 | `python3 bankperm/predict_board_2.py --jobs 2` | `board_prediction_2.json` (committed before the runs; do not commit a changed one) | 58.7 s (`seconds`) |

The scripts check their own assumptions and either stop or record the result in
their JSON (`checks`, `failures`, `all_ok`, `psnr_checks`): the permuted windows
are the original's with permuted columns, the fast objective equals
`predict_w4.window_cycles`, the original counts equal
`denoise/test_set_counts.json`, PSNR equals each export's `int_eval.json`, and
every transcribed board value is on the line it cites. In the JSON files of
this folder every one of these checks passes.

## Where each number of `PAPER_EN.md` comes from

Percentages in the paper are the JSON values rounded half-up to the digits shown; differences in points are differences of the unrounded pooled savings. The rewrite of 2026-10-19 (afternoon) reorganised the paper around the tap-to-bank layout (L0–L3); the section numbers below are those of that draft.

| Paper | Source (file → field) |
|---|---|
| Title, abstract, keywords | identical to `ABSTRACT_IWEICT.md` (Title, Abstract, Keywords); its numbers: 7.02 / 7.60 `b32_board.json` `savings_rep1.*.board_pct`; 9.20 and 9.93 `results_2.json` `networks["B-32 ReLU + QAT s1"].summary_79.w4.L2/L3.pooled_pct` (9.2011, 9.9262); 7.46 and 8.10 `stats_2.json` `sets["79"].layouts.frozen/multistart.pooled_saving_pct` (7.4645, 8.0952; equal to `baselines.json` `summary["79"].methods.frozen_published/multistart_published` and to `results_2.json` L1 and `L1_multistart`); "this order held on all nine networks": `results_2.json` `verdicts.H5`, `verdicts.H6` (`networks`: the nine with C mod 4 = 0); "no layout changed the count where the shape condition says it cannot": `results.json` `verdicts.H1` (L1) and `results_2.json` `verdicts.H4` (L2, L3) |
| Sec. I related work and the novelty search | `references.json` (`paper_n` is the [n] of `PAPER_EN.md`, `n` the [n] of `RELATED_WORK_EN.md`; they differ), `verified`, `how_this_work_differs`, `novelty_threats`. The search covered the folded channel relabeling; the skew itself is skewed storage [7] |
| Sec. II, eq. (1), fill and drain | `denoise/predict_w4.py` docstring; `denoise/w4_gaps.py` (rule), `denoise/w4_gaps.json` (`rule_holds`: board 66/66, RTL sample 66/66; `networks`: A, B, B-32 maxout, B-32 ReLU, all on 05.png, `denoise/w4_prediction.json` `image`); the form of g from RTL simulation of the 45-channel network: commit b37f971 (message); conv1 constant 17: `b32_board.json` `fill_drain_rule`; W = 2 only in RTL simulation: `denoise/README_KO.md` (W=2 section, "보드 측정 전"), b37f971 |
| Sec. II, condition (2) and the W regimes (K = 288: 144 against 145 at W = 2 and 73 at W = 4) | `bounds.json` `networks.*.layers[]`: `K`, `COUT`, `max_compute`, `floor_w1/2/4`, `can_pay_w1/2/4` |
| Sec. III, bank of a tap, L1 fold (conv1..conv(L−2), both maps of maxout/averaging) | `fold.py` docstring, `PROTOCOL.md` (bank of a tap), `perms.json` `networks.*.fitted[].class_sizes`, `DEVIATIONS.md` |
| Sec. III, L2 (slot s·N + (p + s) mod N, 3/2/2/2, partial-sum bound, N = 45: L2 = L0, no RTL change) | `skew_count.py` docstring and `skew_order`; `skew_count.json` `exactness.argument`; `PROTOCOL_2.md` L2; `skew_export_check.json` `export.config_bins.conv*_config.bin.banks_of_each_channel` (every channel's nine taps 3/2/2/2 over the banks), `layout_manifest.tap_order_semantics` (windows `x[:, tap_order]`, weight columns `w[:, tap_order]`, bias unchanged); one bitstream: `board_prediction_2.json` `board` (core ID 0x4d410303) |
| Sec. III, L3 | `PROTOCOL_2.md` L3; `DEVIATIONS_2.md` 1–2; `perms_2.json` `recipe`, `networks.*.fitted[]` |
| Sec. III, fitting (2048 windows, 400 proposals, Cal-1, Cal-3, 2005 vs 401 evaluations; Frozen = the recipe) | `PROTOCOL.md`; `perms.json` `H0`; `baselines.json` `calibrations.C1`, `calibrations.C3`, `budget`; L3: `perms_2.json` `recipe` |
| Sec. III, function preserved | L1: `fold_check.json` `networks.*.images[]` (`png_identical` on Set12 05.png and BSD68 test001.png; `frozen_zip.config_bins_byte_identical`); L2 and L3 on every window of every layer of 05.png, every network: `results_2.json` `networks.*.function_preservation_05png` (`L2_all_layers_equal`, `L3_all_layers_equal_up_to_column_order`, `L3_folded_denoised_image_identical`, `windows_per_layer`; `DEVIATIONS_2.md` 5); the board driver's skew path: `skew_export_check.json` `emulation[]` (05.png and test001.png: `output_identical`, `png_identical`, every layer `accumulators_identical`), `parts_ok` |
| Fig. 1 | `figures/fig1_layouts.py` (window captured by `denoise/predict_w4.layer_windows`; Frozen classes from `research/q1_codesign/bank_export_perm.json`, checked against `perms.json`; m 48 → 44 under Frozen, 16 of 32 channels change bank: printed by the script) |
| Sec. IV networks: 29.54 dB, 37–55% nonzero | `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json` `images[0].psnr_denoised`, `images[0].layers[conv2..conv9].nonzero_fraction` (0.372–0.548) |
| Sec. IV, 79 images and paired bootstrap 95% intervals over images | `results_2.json` `headline`, `bootstrap` (10,000 resamples, `np.random.default_rng(0)`, one index matrix for every network, width and layout; `DEVIATIONS_2.md` 4); `stats_2.json` `bootstrap` (same generator, per set) |
| Sec. IV board: WNS +0.130 ns, 11,151 LUTs, 68 RAMB36 + 6 RAMB18 (71 BRAM36-eq. of 140), no DSP | `denoise/board_runs/w4_build/routed_timing.rpt`, `routed_utilization.rpt` (top row `system_wrapper`); both written in `build/zed_v4_p16_t4_w4_1792234898`, the build `denoise/README_KO.md` l. 140 names for the 2026-10-17 runs and the canary note (`research/q1_codesign/PHYSICAL_W4_CANARY_RESULT_20261018_KO.md` l. 35–36) gives with SHA-256 11641ab… |
| Sec. IV: 50 MHz, the preset's clock; one bitstream for all layouts | `board_transcribed.json` `fclk_mhz`, `core_id`; `denoise/w4_measured.json`; `scripts/run_board_xsdb.tcl` (comment above `WM_FCLK_MHZ`) |
| Sec. IV: transcribed board cycles; only an earlier run of the Original committed raw | `board_transcribed.json`; `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json`; `denoise/board_runs/q1_layouts/` absent (checked 2026-10-19) |
| Sec. IV: PSNR reproduced on all 80 images | `results.json` `networks.*.psnr_checks`; `results_2.json` `networks.*.psnr_checks` |
| Sec. IV, what was fixed when (6dc0e60, 9cf9c79, c2299e2, 951c8f1, with times) | `git log` and GitHub push records (table above) |
| Sec. V-A and Table I (totals and conv2–9 sums) | `b32_board.json` `board_vs_prediction.repeats[0]` (rep 1: `{original,frozen,multistart}.{total,conv2_9}.board`, `in_stall` 0, `predicted` equal: 13,289,030 / 11,421,202; 12,355,814 / 10,487,986; 12,278,419 / 10,410,591), equal to `layouts.*.total.exact_w4` and `.total.conv2_9.exact_w4`; savings 7.02 / 7.60 (`savings_rep1.*.board_pct`) and 8.17 / 8.85 (100 · (11,421,202 − conv2–9) / 11,421,202: 8.1709, 8.8486); `repeats[]` (Frozen rep 3: 12,355,826, IN_STALL 12; `conv1_plus_conv10_derived`), `summary` (63 / 63 exact, 21 labelled out of sample, nine independent: see the table above), `earlier_committed_run`; 90 layer runs without mismatch: `board_transcribed.json` `oracle` |
| Sec. V-A: what is in sample | fill-and-drain rule read off runs that include the Original's layers: `denoise/w4_gaps.json` `networks["B-32 ReLU + QAT"]`, commit 6dc0e60; conv1 and conv10 the same in every layout: `b32_board.json` `sources.*.permuted_outputs` |
| Sec. V-A: board runs pre-registered and under way (no result claimed) | `PROTOCOL_2.md` "Board runs (prospective)"; `board_prediction_2.json` (7312a84; `images` 05–08, `layouts` original, frozen, multistart, skew; `predictions`) |
| Sec. V-B, H0–H3 (1.09–10.80%, 3.36–7.37% on five, 0.022%; signs known for B, maxout s1, board network) | `results.json` `networks.*.summary.w{2,4}.headline_79.pooled_pct`, `verdicts.H1–H3`; H0: `perms.json` `H0`; known signs: `PROTOCOL.md` "What was known"; fold: `fold_check.json`; the 45-channel deviation: `DEVIATIONS.md`. The same L1 values are in `results_2.json` (`cross_checks`: L0 and L1 totals equal `results.json` on all 80 images) |
| Sec. V-B, H4 | `results_2.json` `verdicts.H4.checked` (W = 1 on all ten; W = 2 on A and B-32 ReLU s1–s3; `L2_equals_L0_all_80`, `L3_equals_L0_all_80`, `every_layer_too`) |
| Sec. V-B, H5 (0.90–2.36 points) | `results_2.json` `verdicts.H5.per_network.*.L2_minus_L1_pct_points` (0.8960 B-32 ReLU s3 – 2.3580 A) |
| Sec. V-B, H6 (0.48–1.18 points, every image, board network 0.73 [0.70, 0.75]) | `results_2.json` `verdicts.H6.per_network.*.L3_minus_L2_pct_points` (0.4798 maxout s1 – 1.1791 B); `networks.*.summary_79.w4.L3_minus_L2.images_L3_below_L2` = 79 on all nine; `verdicts.H6.b32_relu_s1_interval` [0.7048, 0.7466], point 0.7251 |
| Sec. V-B, W = 2 (not a hypothesis: L3 > L2 > L1 on five networks, L3 − L2 0.46–0.85) | `results_2.json` `networks.{B + QAT, B-32 maxout s1–s3, B-32 averaging s2}.summary_79.w2` (`L1/L2/L3.pooled_pct`; `L3_minus_L2.pooled_pct_points` 0.4586 maxout s1 – 0.8533 maxout s2) |
| Sec. V-B, no image counted more cycles under any layout at any W | `results_2.json` `networks.*.per_image_totals` (no L1, L2, L3 or Multi-start total above L0 on any of the 80 images at W = 1, 2, 4; checked by a scratch script); `summary_79.*.images_saving_le_0` = 0 wherever (2) allows a gain |
| Fig. 2 (W = 4 and W = 2, L1–L3 per network, 95% intervals at most ±0.39 points) | `figures/fig2_networks.py` (`results_2.json` `per_image_totals`, `summary_79`, `bootstrap_95_pct`; `bounds.json`); largest half-width 0.389 (B-32 ReLU s1, L3, W = 4), 0.146 at W = 2 |
| Sec. V-C: per-image order on the board network | L3 below L2 on 79 / 79: `results_2.json` `networks["B-32 ReLU + QAT s1"].summary_79.w4.L3_minus_L2.images_L3_below_L2`; L2 below Frozen and Multi-start on 79 / 79: `stats_2.json` `sets["79"].differences_pp["skew - frozen"]`, `["skew - multistart"]` `images_where_a_saves_more` |
| Sec. V-C: 82.6% of the perfect-balance saving; 05.png 9.39 / 8.64 / 7.02 / 7.60 / 11.49 | share = 100 · Σ(L0 − L3) / Σ(L0 − perfect balance) over the 79 = L3 pooled / perfect-balance pooled (the same L0 sum, 2,516,898,515: `stats_2.json` `sets["79"].original_cycles` = the L0 sum of `results_2.json`): 9.9262 / 12.0156 = 82.61%; 05.png: `results_2.json` `summary_79.w4.L3["05.png"]` 9.3861, `.L2["05.png"]` 8.6444, `.L1["05.png"]` 7.0225, `.L1_multistart["05.png"]` 7.6049 (counts, equal after rounding to the board's 7.02 and 7.60); perfect balance `b32_board.json` `headroom_w4.perfect_balance.saving_pct` 11.4912 |
| Sec. V-C: baselines and the search budget (Frozen's seed the worst of five; greedy beat Multi-start on four of five seeds) | `baselines.json` `summary["79"].methods`: `window_greedy_self` 8.4517 (L1 fitted per image), `sense_lpt` 4.8939 (the best of the three Sense-like rows), `meannnz_lpt` 3.6889 (the best Cal-1 density deal); `frozen_recipe_c1.per_seed` (seed 42 = Frozen, 7.4645, the lowest of five); `summary["77"].methods.greedy_budget_c3.per_seed` against `multistart_c3.per_seed` (greedy higher for seeds 42, 202, 303, 404; lower for 101) |
| Table II (eight rows) | pooled and interval: `stats_2.json` `sets["79"].layouts`: `meannnz_lpt` 3.6889 [3.4957, 3.8823], `frozen` 7.4645 [7.1584, 7.7787], `multistart` 8.0952 [7.8018, 8.3939] (`clean` false: Cal-3 contains Set12 02–03), `skew` 9.2011 [8.8248, 9.5796], `perfect_balance` 12.0156 [11.5906, 12.4426]; L3: `results_2.json` `networks["B-32 ReLU + QAT s1"].summary_79.w4.L3` 9.9262 [9.5398, 10.3155]; Sense-like and fitted per image: `baselines.json` as above, no interval computed. Share: `baselines.json` `summary["79"].methods.*.headroom_captured_pct` (30.70, 40.73, 62.12, 67.37, 70.34); L2 76.58 and L3 82.61 = pooled / 12.0156 (same L0 sum) |
| Fig. 3 | `figures/fig3_per_image.py` (`baselines.json` `per_image` perfect balance, `results_2.json` `per_image_totals` L3, `skew_count.json` L2, `b32_testsets.json` Frozen and Multi-start; the script checks that all four files agree on L0 and that `results_2.json`'s L1, L2 and `L1_multistart` equal the other files on every image) |
| Sec. V-D: fit time 7.1–28.8 s (L1), 2.9–18.7 s (L3) | `perms.json` `networks.*.seconds`; `perms_2.json` `networks.*.seconds` (= `results_2.json` `runtimes.fit_L3_seconds`) |
| Sec. V-D: host 31 ms, core 266 ms, 6.8% back to back, all 7.60% with overlap, 4.2 ms for the skew's reordering; what the bound leaves out | `host_time.json` `amdahl.multistart_vs_original_host_per_op` (`host_ms` 30.5945, `core_orig_ms` 265.7806, `core_saving_pct` 7.6048, `back_to_back.saving_pct` 6.8198, `perfect_overlap_over_images.saving_pct` 7.6048); 4.2 ms = `skew_count_vs_original_host_per_op_plus_skew_gather.host_ms` 34.8054 − 30.5945; `machine`, `threads`, `caveats` (transfer not counted; x86 server, not the Zynq's ARM cores), `jtag_harness` (315.0 s of XSDB time, excluded) |
| Sec. VI, selection: what was seen before PROTOCOL_2 | `PROTOCOL_2.md` "What was known before this protocol"; `skew_count.json` `networks` (B-32 ReLU s1 on 80 images; A, B, maxout s1, 10 × 45 on 05.png); Multi-start chosen after its BSD68 counts: `baselines.json` `multistart_selection` |
| Sec. VI IN_STALL counter | commit b37f971 (message) |

The tables of `PAPER_EN.md` were generated from these fields by hand or by
scratch scripts that are not committed; every cell can be checked against the
field named above. Table numbers in the current draft: Table I (board, totals and
conv2–9 sums), Table II (eight layouts of the board network with intervals; it
replaces the earlier nine-row baseline table: the random-layout and equal-budget
rows went into the text or out, the L3 row and the intervals came in). Figures:
Fig. 2 is now L1, L2 and L3 per network at W = 4 and W = 2 from `results_2.json`
(per-image range lines replaced by bootstrap bars; colour means the layout, not
W); Fig. 3 adds L3. No longer printed: the random layouts (−5.43 to +1.73%), the
density shares 21–33%, the 0.63-point decomposition of Multi-start's lead, the
mechanism counts of 05.png (conv9 43.04 → 35.10) and the per-image ranges of
Frozen and Multi-start; their sources are unchanged (`baselines.json`,
`b32_board.json` `mechanism`, `b32_testsets.json`).

## Building the manuscript

    python3 bankperm/figures/fig1_layouts.py; python3 bankperm/figures/fig2_networks.py; python3 bankperm/figures/fig3_per_image.py
    python3 iweict2026/build_docx.py --tpl iweict2026/template_word.docx --src bankperm/PAPER_EN.md --out bankperm/PAPER_EN.docx --lang en --col-fig-cm 8 --authors "..." --affil "..." --email "..." --author2 "..." --affil2 "..." --email2 "..." --ack "..."
    soffice --headless --convert-to pdf --outdir bankperm bankperm/PAPER_EN.docx   # then rename to PAPER_EN_preview.pdf

The builder fills the IWEICT Word template; lines starting with `>` (the
"Before submission" box) are dropped. Without `--authors`, `--affil` and `--ack`
it prints the Korean IWEICT defaults, so pass them even as placeholders
(`--authors "Lee Yoo Joon"`, the Yeungnam affiliation, `--email "(e-mail)"`, the
advisor placeholders `--author2 "(Advisor name)"`,
`--affil2 "(Dept. name of organization); (Name of organization); (City, Country)"`,
`--email2 "(e-mail address)"` and the IITP `--ack`; the copy with the author's
e-mail is kept outside the repository). With these, the three figures at 8 cm
(`--col-fig-cm 8`) and the rewrite of 2026-10-19 (afternoon), the LibreOffice
build is exactly four A4 pages with no trailing page (the last right column ends
about two lines above the bottom margin, so there is no room to add text). The
committed `PAPER_EN.docx` and `PAPER_EN_preview.pdf` are of the earlier draft and
must be rebuilt from the current `PAPER_EN.md` and figures. The template's last,
empty section-break paragraph keeps the numbered references style: LibreOffice
prints nothing there, but check in Word that no "[11]" follows the references, and
that Word, which may lay the template out differently, also gives four pages.

## Files

| File | Role |
|---|---|
| `PROTOCOL.md`, `bounds.py`, `bounds.json` | pre-registered protocol and shape-only bound (c2299e2); do not edit |
| `DEVIATIONS.md` | where the protocol needed a choice (45-channel network) |
| `fit.py` → `perms.json` | the recipe on all ten networks; H0 |
| `fold.py` → `fold_check.json` | folded exports are the same function (Set12 05, BSD68 test001) |
| `evaluate.py` → `results.json` | the ten-network evaluation; H1–H3 |
| `b32_board.py`, `board_transcribed.json` → `b32_board.json` | board vs exact prediction on 05.png |
| `b32_testsets.py` → `b32_testsets.json` | Original, Frozen, Multi-start on 80 images |
| `baselines.py` → `baselines.json` | density, Sense-like, random, equal-budget baselines, bounds |
| `skew_count.py` → `skew_count.json` | data-free skewed tap layout, counted after the study (B-32 ReLU s1 on 80 images; A, B, maxout s1, 10 × 45 on Set12 05.png); oracle exactness check |
| `PROTOCOL_2.md`, `DEVIATIONS_2.md`, `PROTOCOL_2_ADDENDUM.md` | second pre-registered protocol (951c8f1; L0–L3, H4–H6, board runs), the readings it needed, and the added L3 board runs; do not edit the protocol |
| `evaluate_2.py` → `perms_2.json`, `results_2.json` | the L3 fit and the PROTOCOL_2 evaluation on ten networks, 80 images, W = 1, 2, 4, with bootstrap intervals and function checks; H4–H6 |
| `stats_2.py` → `stats_2.json` | bootstrap intervals for the board network's layouts and baselines (no re-count) |
| `host_time.py` → `host_time.json` | host work per image against core time; end-to-end bounds |
| `export_layout.py`, `prepare_layouts.py`, `check_skew_export.py` → `skew_export_check.json` | the skew's (and L3's) export and host path, and its check |
| `predict_board_2.py` → `board_prediction_2.json`; `compare_board_2.py` | exact predictions of the PROTOCOL_2 board runs (committed before them) and the comparison to run after them |
| `figures/fig{1_layouts,2_networks,3_per_image}.py` → `.png`, `.pdf` | the paper's Fig. 1–3, from the JSON files above (Fig. 2 and 3 redrawn from `results_2.json` and the board network's files; committed in WIP 0887924, not reviewed) |
| `references.json`, `RELATED_WORK_EN.md` | checked references and the related-work draft |
| `PAPER_EN.md` | the IWEICT 2026 paper (4 pages); title and abstract identical to `ABSTRACT_IWEICT.md` |
| `ABSTRACT_IWEICT.md` | title and abstract for the submission form |
| `PAPER_EN.docx`, `PAPER_EN_preview.pdf` | an earlier draft built into the IWEICT Word template, and its LibreOffice PDF (to be rebuilt) |
| `IWEICT_INSERT_EN.md` | two to three sentences for the IWEICT paper, with where to put them |
