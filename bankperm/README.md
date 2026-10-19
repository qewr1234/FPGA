# bankperm: offline channel-to-bank permutation for the banked W = 4 core

This folder holds the evidence and the manuscript for one result. On the banked
window-MAC core (P = 16 output lanes, T = 4 banks, tap t of a window in bank
t % 4, sparse mode), the bank of a tap in a 32- or 64-channel layer is its
channel position mod 4. So the order of a layer's input channels decides which
channels share a bank, and with it how long each window waits for its fullest
bank. A permutation of the hidden channels, fitted offline on calibration
images and folded into the producer's filters, bias and requantization and the
consumer's weights, leaves the bitstream and the integer output unchanged and
changes only the cycles. (Because the host builds the windows, a reordering of
the taps inside each window is also exact. One data-free tap layout, the skew,
was counted after the study (`skew_count.py`, not run on the board) and saves
more than both fitted relabelings on the board network; the rest of that larger
space is not evaluated here, see the box at the top of `PAPER_EN.md`.) The folder records:

- where a permutation can change the cycles at all, from the layer shapes alone (`bounds.py`);
- the board run of three layouts of B-32 ReLU + QAT s1 (`dn_d10_c32_us_fx_qat`) on Set12 05.png at W = 4, and the exact prediction of every measured number (`b32_board.py`);
- their counts on all 80 test images (`b32_testsets.py`);
- a pre-registered study of one fixed recipe on all ten networks of `denoise/count_test_sets.py` (`PROTOCOL.md`, `fit.py`, `fold.py`, `evaluate.py`);
- baselines on the board network (`baselines.py`);
- a count of the data-free skewed tap layout, after the study (`skew_count.py`);
- the paper's three figures (`figures/`, drawn from the JSON files of this folder);
- the related work (`references.json`, `RELATED_WORK_EN.md`), the journal-brief draft (`PAPER_EN.md`, built as `PAPER_EN.docx` and `PAPER_EN_preview.pdf`) and a short insert for the IWEICT paper (`IWEICT_INSERT_EN.md`).

## Measured, counted, transcribed

| Kind | What | Where |
|---|---|---|
| Measured on the board, committed raw report | the earlier W = 4 run of the Original export of the board network on Set12 05.png (13,289,042 cycles, 12 of them IN_STALL in conv5; 315.0 s of JTAG debugger time over its ten layers) | `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json`, `denoise/w4_measured.json` |
| Measured on the board, **transcribed** | the canary run of the Original and three repeats of Original, Frozen and Multi-start (2026-10-18) | `board_transcribed.json`: every value with file, line and the exact quote from `research/q1_codesign/PHYSICAL_W4_*_20261018_KO.md`. The raw `report.json` files, XSDB logs and PNG digests are **not in the repository**; Frozen's per-layer board cycles were never given, only its total and its conv2–9 sum |
| Predicted exactly | per-window count + per-layer fill and drain (`denoise/w4_gaps.py`; conv1 a measured constant, 17) | `b32_board.json` `layouts.*.layers[].exact_w4`, compared in `board_vs_prediction`. Its `status` "out of sample" is by layout: Multi-start conv10 and the totals are labelled out of sample although conv1 and conv10 see the same windows in every layout (only conv1–conv8 outputs are permuted, `sources.*.permuted_outputs`), so of its 21 out-of-sample comparisons nine are independent (Multi-start conv2–conv9, Frozen conv2–9 sum) |
| Counted | per-window count of `denoise/predict_w4.window_cycles` (sparse mode) over the windows of the host emulation (`scripts/run_denoise.py`), fill and drain left out | everything else: `b32_testsets.json`, `results.json`, `baselines.json`, `skew_count.json`, the counts in `b32_board.json` |
| From layer shapes only | where a permutation can pay | `bounds.json` |

All counts are at σ = 25 with one noise draw per image (`test_noise` seed 0).
W = 2 numbers are counts only; no W = 2 board run exists.

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

`PROTOCOL.md`, `bounds.py` and `bounds.json` must not be edited. The one place where
the protocol could not be applied word for word (the 45-channel network) is in
`DEVIATIONS.md`.

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

The scripts check their own assumptions and either stop or record the result in
their JSON (`checks`, `failures`, `all_ok`, `psnr_checks`): the permuted windows
are the original's with permuted columns, the fast objective equals
`predict_w4.window_cycles`, the original counts equal
`denoise/test_set_counts.json`, PSNR equals each export's `int_eval.json`, and
every transcribed board value is on the line it cites. In the JSON files of
this folder every one of these checks passes.

## Where each number of `PAPER_EN.md` comes from

Percentages in the paper are the JSON values rounded half-up to the digits shown. Per-image ranges in Table V are recomputed from `baselines.json` `per_image` at full precision, not from the 4-decimal `min_pct`/`max_pct` fields (6.524953 is stored as 6.525 and must print as 6.52; 1.764975 as 1.765, printing 1.76).

| Paper | Source (file → field) |
|---|---|
| Abstract, Sec. I | the sources below |
| Sec. II, eq. (1), fill and drain | `denoise/predict_w4.py` docstring; `denoise/w4_gaps.py` (rule), `denoise/w4_gaps.json` (`rule_holds`: board 66/66, RTL sample 66/66); the form of g from RTL simulation of the 45-channel network: commit b37f971 (message); conv1 constant 17: `b32_board.json` `fill_drain_rule`; W = 2 only in RTL simulation: `denoise/README_KO.md` (W=2 section, "보드 측정 전"), b37f971 |
| Sec. II text and Table I | `bounds.json` `networks.*.layers[]`: `K`, `COUT`, `max_compute`, `floor_w1/2/4`, `can_pay_w1/2/4` |
| Sec. III (fold; 45-channel bank rule) | `fold.py` docstring, `PROTOCOL.md` (bank of a tap), `perms.json` `networks.*.fitted[].class_sizes`, `DEVIATIONS.md` |
| Sec. III (Multi-start: data and budget; Cal-1 and Cal-3 are the C1 and C3 of the JSON) | `baselines.json` `calibrations.C1`, `calibrations.C3`, `budget`, `multistart_selection`; fit time 7.1–28.8 s: `perms.json` `networks.*.seconds` |
| Sec. IV networks: 29.54 dB, 37–55% nonzero | `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json` `images[0].psnr_denoised`, `images[0].layers[conv2..conv9].nonzero_fraction` (0.372–0.548) |
| Sec. IV board: WNS +0.130 ns, 11,151 LUTs, 68 RAMB36 + 6 RAMB18 (71 BRAM36-eq. of 140), no DSP | `denoise/board_runs/w4_build/routed_timing.rpt`, `routed_utilization.rpt` (top row `system_wrapper`); both written in `build/zed_v4_p16_t4_w4_1792234898`, the build `denoise/README_KO.md` l. 140 names for the 2026-10-17 runs and the canary note (`research/q1_codesign/PHYSICAL_W4_CANARY_RESULT_20261018_KO.md` l. 35–36) gives with SHA-256 11641ab… |
| Sec. IV: 50 MHz, core ID 0x4d410303; the preset's clock | `board_transcribed.json` `fclk_mhz`, `core_id`; `denoise/w4_measured.json`; `scripts/run_board_xsdb.tcl` (comment above `WM_FCLK_MHZ`) |
| Sec. IV: commits | `git log` and GitHub push records (table above); the skew count: 2928d28 (2026-10-19 03:54) |
| Sec. IV: PSNR reproduced on all 80 images | `results.json` `networks.*.psnr_checks` |
| Sec. V-A and Table II | `b32_board.json`: `layouts.{original,frozen,multistart}.layers[].exact_w4` and `.total`; `board_vs_prediction.original_rep1_layers`, `multistart_rep1_layers`, `repeats[]` (Frozen rep 3: 12,355,826, IN_STALL 12; `conv1_plus_conv10_derived`), `summary` (63 / 63 exact, 21 labelled out of sample, nine independent: see the table above), `earlier_committed_run`; the Count and Fill/drain rows of Table II: `layouts.*.total.count.w4` and `layouts.*.total.fill_drain_w4` (`board_vs_prediction.savings_rep1`: 1,010,611 measured vs 1,010,573 `count_only`) |
| Sec. V-A: 90 layer runs, no mismatch; PNGs identical | `board_transcribed.json` `oracle`, `png_sha256.note` |
| Sec. V-A mechanism | `b32_board.json` `mechanism.layers.conv{5,8,9}` (`mean_max_bank`, `floor_bound_share`), `headroom_w4` (11,761,449 / 11.49%, 11,436,032 / 13.94%, shares 0.6618 and 0.6111); the window of Fig. 1 (m 48 → 44 under Frozen): printed by `figures/fig1_layouts.py` |
| Sec. V-C, first paragraph (formerly V-B; the former Table III is text) | `b32_testsets.json` `summaries["79 without 01.png"].frozen.w4`, `summaries["77 without Set12 01-03"].multistart.w4` and `.image_layers_worse_w4` (1 for Frozen of 79 × 8 = 632 fitted image-layers; 0 for Multi-start of 77 × 8 = 616), `images[].worse_layers_w4` (BSD68 test028 conv3, −1.558915), `rank_of_05`, `summaries["77 without Set12 01-03"].multistart_below_frozen_w4` (74); bounds: `baselines.json` `summary["79"].perfect_balance`, `.floor` |
| Sec. V-B and Fig. 2 (formerly Sec. V-C and Table IV) | `results.json` `networks.*.summary.w{2,4}.headline_79` (`pooled_pct`, `min_pct`, `max_pct`, `image_layers_worse`: 16 for 10 × 45 at W = 2, at most 3 on the other networks at W = 2 and 4), `.per_layer_pooled_79` (45-channel conv7 at W = 2: −0.0001%), `layers_that_cannot_pay_unchanged`, `verdicts.H1–H3`; H0: `perms.json` `H0`; which signs were already known (H2 new for seven networks): `PROTOCOL.md` "What was known"; fold: `fold_check.json` (`frozen_zip`, `networks.*.images[]`); the deviation: `DEVIATIONS.md` |
| Sec. V-C and Table III (formerly Sec. V-D and Table V) | `baselines.json` `summary["79"].methods` and `summary["77"].methods` (`pooled_pct`, `headroom_captured_pct`; five-seed rows `pooled_pct_mean/min/max`, `per_seed`), per-image ranges from `per_image` (see above), `random_median.pooled_range_of_20`, `density_vs_window` (58%); density shares 21–33%: `headroom_captured_pct` of `density_rr`, `density_snake`, `meannnz_lpt` (79) and `*_c3` (77); fitted 62–68.5%: the deployable fitted rows of Table III. Table III's "Density, smallest total" is `meannnz_lpt`, "Sense-like, smallest total" `sense_lpt`, "Recipe per test image" `window_greedy_self` |
| Sec. V-C search budget (0.63 = 0.15 + 0.29 + 0.32 − 0.07 − 0.06 points; 4 of 5 seeds) | `baselines.json` `summary["77"].methods`: `frozen_published` 7.4784 → `frozen_recipe_c1.pooled_pct_mean` 7.6310 → `greedy_budget_c1` mean 7.9247 → `greedy_budget_c3` mean 8.2431 → `multistart_c3` mean 8.1730 → `multistart_published` 8.1091 (seed 42, the lowest of five, as Frozen's seed 42 is in `frozen_recipe_c1.per_seed`); `greedy_budget_c3.per_seed` vs `multistart_c3.per_seed` |
| Sec. VI | `references.json`: `paper_n` is the [n] of `PAPER_EN.md`, `n` the [n] of `RELATED_WORK_EN.md` (they differ); `verified`, `how_this_work_differs`, `novelty_threats` |
| Sec. VII wall-clock (315.0 s, 0.266 s, 20.2 ms, 0.006%) | `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json` `images[0].layers[].wall_seconds` summed (its `host_seconds` time only `run_layer`, not im2col or requantization, so the paper does not quote them); core time = cycles / 50 MHz from `b32_board.json` |
| Sec. II skew (slot s·N + (p + s) mod N, 3/2/2/2, partial-sum bound); Sec. III (N = 45: the conventional layout is the skew) | `skew_count.py` docstring and `skew_order`; `skew_count.json` `exactness.argument` |
| Sec. V-C skew paragraph, Table III skew row, abstract (9.20% against 7.46% and 8.10%) | `skew_count.json` `board_network.saving_percent_79_images_other_than_01.w4` (`pooled` 9.2011, `median` 9.0239, `min` 5.7032, `max` 13.6553); share 76.6 = 100 · Σ(conventional − skewed) / Σ(original − perfect balance) over the 79 images other than Set12 01.png, with `conventional`/`skewed` `w4` from `skew_count.json` `networks["B-32 ReLU + QAT s1"].images` and `original`/`perfect_balance` from `baselines.json` `per_image` (the conventional and original totals agree on all 79; 76.58%); fewer cycles than Frozen and Multi-start on 79 / 79: the same `w4` against `baselines.json` `per_image` `frozen_published`, `multistart_published` (equal to `b32_testsets.json`); on the 77 images other than Set12 01–03: 9.22% (same fields) against `baselines.json` `summary["77"].methods.multistart_published` 8.1091; the abstract's 7.46% and 8.10%: `summary["79"].methods.frozen_published` 7.4645 and `.multistart_published` 8.0952; 05.png: `images["Set12 05.png"]` (12,139,748 vs 13,288,456: 8.64%; 7.02% and 7.60%: Table II count row); A, B, maxout s1 on 05.png: `skew_count.json` `networks.{A, "B + QAT", "B-32 maxout + QAT s1"}.images["Set12 05.png"]` `w4` (10.01, 10.91, 5.61%) against `results.json` `networks.*.per_image["Set12/05.png"].w4` (7.67, 9.36, 3.47%); 10 × 45: `layers_skewed` 0; oracle check: `exactness.checked`, `layers_differing` (empty) |
| Fig. 1, Fig. 2, Fig. 3 | `figures/fig1_layouts.py` (window captured by `denoise/predict_w4.layer_windows`; Frozen classes from `research/q1_codesign/bank_export_perm.json`, checked against `perms.json`), `figures/fig2_networks.py` (`results.json`, `bounds.json`), `figures/fig3_per_image.py` (`baselines.json` `per_image`, `skew_count.json`, `b32_testsets.json`); each script's docstring says what it checks before plotting |
| Sec. VII tap-level layouts | `skew_count.json` (`networks`: B-32 ReLU s1 on 80 images, four networks on Set12 05.png only; `exactness`) |
| Sec. VII IN_STALL counter | commit b37f971 (message); the rule in RTL simulation: `denoise/w4_gaps.json` `rule_holds.rtl_sample` |

The tables of `PAPER_EN.md` were generated from these fields by a scratch script
that is not committed; every cell can be checked against the field named above.
The skew numbers of the paper come from `skew_count.json` (2928d28). The box at
the top of `PAPER_EN.md` also names earlier review counts (the skew on 8 images of
B and maxout s1, skew plus a channel fit) that are not committed and that the
paper does not cite. Table numbers changed: the former Table IV is Fig. 2, the
former Table V is Table III.

## Building the manuscript

    python3 bankperm/figures/fig1_layouts.py; python3 bankperm/figures/fig2_networks.py; python3 bankperm/figures/fig3_per_image.py
    python3 iweict2026/build_docx.py --tpl iweict2026/template_word.docx --src bankperm/PAPER_EN.md --out bankperm/PAPER_EN.docx --lang en --col-fig-cm 8 --authors "..." --affil "..." --email "..." --ack "..."
    soffice --headless --convert-to pdf --outdir bankperm bankperm/PAPER_EN.docx   # then rename to PAPER_EN_preview.pdf

The builder fills the IWEICT Word template; lines starting with `>` (the
"Before submission" box) are dropped. Without `--authors`, `--affil` and `--ack`
it prints the Korean IWEICT defaults, so pass them even as placeholders
(`PAPER_EN.docx` was built with "(Author names)", "(Affiliation)", "(e-mail)" and
"(Acknowledgment)"). With the three figures at 8 cm (`--col-fig-cm 8`) the
LibreOffice build is five A4 pages. The target journal's own template is still
needed (see the box at the top of `PAPER_EN.md`).

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
| `figures/fig{1_layouts,2_networks,3_per_image}.py` → `.png`, `.pdf` | the paper's Fig. 1–3, from the JSON files above |
| `references.json`, `RELATED_WORK_EN.md` | checked references and the related-work draft |
| `PAPER_EN.md` | journal-brief draft (IEEE ESL or TCAS-II) |
| `PAPER_EN.docx`, `PAPER_EN_preview.pdf` | that draft built into the IWEICT Word template, and its LibreOffice PDF |
| `IWEICT_INSERT_EN.md` | two to three sentences for the IWEICT paper, with where to put them |
