# Pre-registered protocol: one fixed permutation recipe on every board-class network

Written and committed **before** any channel-to-bank permutation was fitted or
counted on the networks listed below, other than `dn_d10_c32_us_fx_qat` (B-32
ReLU + QAT s1, the network of the Frozen and Multi-start exports on `main`).

## What was known before this protocol

- For B-32 ReLU s1: the Frozen recipe, its W=4 counts on all 80 test images,
  and the W=4 board run of the Original, Frozen and Multi-start exports on
  Set12 05.png (`research/q1_codesign/`, and the review of 2026-10-18).
- From GPT's GPU sweep (`research/q1_codesign/GPU_RESULTS_REVIEW_20261018_KO.md`
  l. 49-50), pooled over BSD68 x sigma 15/25/50, W=4 count, with **other**
  search methods (density sort, greedy, anneal, multi-start), not this recipe:
  B (64-ch ReLU) about 6.6-9.9 % and B-32 maxout s1 about 0.8-4.2 %. So for
  B and maxout s1 the sign at W=4 was already known; for the other seven
  networks, and for every network at W=2, nothing was counted.
- `bankperm/bounds.py` (`bounds.json`, committed with this file): from the
  layer shapes alone, where a permutation can change the count at all.

## Networks

Every network of `denoise/count_test_sets.py` MODELS:
A, B + QAT, B-32 ReLU + QAT s1/s2/s3, B-32 maxout + QAT s1/s2/s3,
B-32 averaging + QAT s2, 10 x 45 ReLU + QAT. No network is added or dropped
after the results are seen.

## The permutation

- Permuted tensors: the outputs of conv1 to conv(L-2), i.e. the input channels
  of conv2 to conv(L-1). The image is never permuted; the output of conv(L-1)
  (the last layer's input, together with the image) is not permuted, because
  the last layer has COUT <= 16 and `bounds.py` shows it can never pay.
- Folding (no run-time reordering): the producer's output channels (weights,
  bias, requant scale; for maxout and averaging layers both maps c and c+C of
  each pooled channel c, with the same permutation) and the consumer's input
  taps are reordered together. The integer function is unchanged for every
  input.
- Bank of a tap: the consumer's im2col order is (ky, kx, channel), tap
  t = s * C_in + p (s the 3x3 position, p the channel position, C_in the
  consumer's input channels including concatenated ones), bank t % 4. For
  C_in % 4 == 0 that is p % 4; for C_in = 45 it is (s + p) % 4. So a
  permutation is an assignment of channels to the four position classes
  p % 4, with the class sizes of the identity layout.

## The recipe (fixed: the Frozen recipe of `scripts/q1_reviewer_bank.py`)

- Calibration: Set12 01.png only, sigma of the network (25), `test_noise`
  seed 0, the board driver's host emulation (`scripts/run_denoise.py`).
  Per fitted layer, 2048 windows drawn without replacement by one
  `np.random.default_rng(42)`, consumed in layer order.
- Objective: mean W=4 window cycles on those windows,
  `max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT)`, with the bank
  of each tap as above.
- Search: `fit_group` as written: start from the identity layout; 400
  proposals, each swapping two channels in different classes, accepted only
  if the objective falls (by more than 1e-10); generator seed 42 + the index
  of the layer among the fitted layers (conv2 -> 0).
- One permutation per network, fitted at W=4, evaluated at W=1, 2 and 4.
  Nothing is tuned per network, per width or after evaluation.

## Evaluation

- All 80 test images (Set12 12, BSD68 68), sigma 25, `test_noise` seed 0,
  host emulation; per image, the per-window count summed over conv1-convL
  (`denoise/predict_w4.window_cycles`, sparse mode) for the original and the
  permuted layout, at W = 1, 2, 4.
- Headline per network and width: the 79 images other than 01.png (range,
  median, pooled saving). 05.png and 01.png are reported separately.
- Function preservation: proven by the folding algebra for every network;
  checked bit for bit in host emulation by exporting each permuted network and
  comparing its output with the original's on Set12 05.png and BSD68 test001
  (both outputs and every layer's accumulators up to the column order).

## Predictions, fixed now

- **H0 (implementation check).** On B-32 ReLU s1 this implementation
  reproduces `research/q1_codesign/bank_export_perm.json` (the published
  Frozen groups) exactly. If it does not, the difference is reported and the
  published groups are used for that network.
- **H1 (structural, must hold exactly).** Where `bounds.json` says "zero"
  (every network at W=1; A and B-32 ReLU s1-s3 also at W=2), the permuted
  count equals the original count on every image.
- **H2.** At W=4 the pooled count over the 79 images falls for every one of
  the ten networks.
- **H3.** At W=2 the pooled count over the 79 images falls for every network
  where `bounds.json` says "can pay" (B, maxout s1-s3, averaging s2, 45-ch).

Any failure is reported as a failure, and the paper text follows the result.
