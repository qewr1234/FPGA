# Pre-registered protocol 2: the skewed layout, skew + relabeling, and the next board runs

Written and committed **before** any of the counts, fits or board runs below were
made. It is a new protocol, separate from `PROTOCOL.md` (H0–H3, all held,
`results.json`); its hypotheses are numbered on from there.

## What was known before this protocol

- `skew_count.json` (2928d28): the skewed layout on B-32 ReLU s1 on all 80 images
  (W=4 pooled saving 9.20% over the 79 images other than Set12 01.png; 0 at W=1
  and W=2) and on Set12 05.png for A, B, B-32 maxout s1 and 10 x 45 (W=4 saving
  10.01%, 10.91%, 5.61%, 0 by construction for 10 x 45).
- Uncommitted exploratory counts made during reviews (scratch files only): the
  skew on 8 images each of B and maxout s1; a channel relabeling fitted under the
  skewed bank rule on 7 images of B-32 ReLU s1 (it added about 0.5–0.8 points over
  the skew). These are disclosed here and are not evidence for H6.
- Nothing was counted for the skew on B-32 ReLU s2/s3, maxout s2/s3, averaging s2,
  nor on more than 05.png for A, B, maxout s1. Nothing with the skew has run on the
  board.

## Layouts

- **L0 conventional:** tap t = s·C + p (s the 3×3 position, p the channel
  position, C the consumer's input channels), bank t mod 4.
- **L1 relabeling:** the PROTOCOL.md recipe's fitted orders (`perms.json`); on
  B-32 ReLU s1 also the published Frozen and Multi-start layouts.
- **L2 skew:** channel p of position s in bank (s + p) mod 4. For C mod 4 = 0 the
  host puts it in slot s·C + (p + s) mod C; for C mod 4 = 1 (10 x 45) the
  conventional layout already has this bank, so L2 = L0 there. As in PROTOCOL.md,
  only the inputs of conv2..conv(L-1) change.
- **L3 skew + relabeling:** the channels' position classes (p mod 4) refitted
  under the skewed bank rule, bank = (s + class) mod 4, with exactly the
  PROTOCOL.md recipe (`bankperm/fit.py` `fit_general`: identity start, 400
  proposals, Set12 01.png, 2048 windows per layer from one
  `np.random.default_rng(42)`, generator seed 42 + fitted-layer index, objective
  the mean W=4 window cycles). For 10 x 45 the skewed rule is its own
  conventional rule, so L3 = L1 there.

All layouts are function-preserving by construction (the same permutation of a
window's taps and of the consumer's weight columns; relabelings also fold into
the producer). Checked: integer-oracle accumulators on every layer of 05.png for
every network and layout; for B-32 ReLU s1, the host driver's own export path
for L2 in emulation (bit-identical output), before any board run.

## Evaluation (counts)

All ten networks, all 80 images (Set12 + BSD68, σ = 25, `test_noise` seed 0),
per image the conv1–convL count at W = 1, 2, 4 for L0–L3 (per-window rule,
`predict_w4.window_cycles`, fill and drain left out). Headline: the 79 images
other than Set12 01.png. Paired bootstrap over images (10,000 resamples, seed 0,
95% percentile interval) for the pooled saving of L1, L2, L3 against L0 and for
the difference L3 − L2.

## Hypotheses, fixed now

- **H4 (structural, must hold exactly).** Wherever `bounds.json` says zero (every
  network at W = 1; A and B-32 ReLU s1–s3 also at W = 2), L2 and L3 count exactly
  as L0 on every image.
- **H5.** At W = 4 the pooled saving of L2 is larger than that of L1 on every
  network with C mod 4 = 0 (nine networks).
- **H6 (the open question).** At W = 4 the pooled saving of L3 is larger than that
  of L2 on every network with C mod 4 = 0, and on B-32 ReLU s1 the 95% bootstrap
  interval of L3 − L2 excludes 0.

Any failure is reported as a failure.

## Board runs (prospective)

On the existing W = 4 bitstream (core ID 0x4d410303; `--w4 --mode 1 --fclk 50`),
B-32 ReLU s1, layouts Original (L0), Frozen, Multi-start and Skew (L2), images
Set12 05.png and Set12 06.png, 07.png, 08.png (never used to calibrate any
layout). Before the runs, the exact per-layer cycles of each run (count + the
`w4_gaps.py` fill-and-drain rule; conv1's measured constant) are committed in
`bankperm/board_prediction_2.json`. A layer is predicted if CYCLES − IN_STALL
equals its prediction exactly; every miss is listed. This bitstream's IN_STALL
does not count starvation at window boundaries, so the exact match, not
IN_STALL = 0, is the test.
