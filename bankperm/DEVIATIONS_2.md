# Where carrying out PROTOCOL_2.md needed a choice

PROTOCOL_2.md is unchanged (commit 951c8f1). These are the points where it had to be
read one way or another to run it, and the reading taken. The code is
`bankperm/evaluate_2.py`; the fit is in `bankperm/perms_2.json` and the counts in
`bankperm/results_2.json`.

## 1. The skewed bank rule inside `fit_general`'s objective

`fit.py` feeds `fit_general` per-window, per-channel nonzero counts split by the
residue (s·C_in) mod 4 of the 3×3 position s (`fit.residue_counts`), which is the
conventional rule. For L3 the same counts are split by s mod 4
(`evaluate_2.skew_residue_counts`): under the skew a channel of class r has its tap at
position s in bank (s + r) mod 4. `fit_general`, `fast_cycles` and `bank_counts` are
used unchanged, with the same identity start, 400 proposals, acceptance rule and seed
42 + fitted-layer index.

Checks (asserted in `fit_network_2`):
- the calibration windows are those of `perms.json`: on every fitted layer the L0 and
  L1 calibration means recomputed from them equal `perms.json`'s exactly;
- on every fitted layer, for the identity, the fitted and one random relabeling, the
  objective equals `predict_w4.window_cycles` on the skewed windows, window by window,
  at W = 1, 2 and 4 (for the identity that is the L2 count);
- every slot's bank (slot mod 4) is (s + class of the channel in it) mod 4;
- the skew of the identity is `skew_count.skew_order`;
- for C_in = 45 the s mod 4 split equals `fit.residue_counts`'s, and the L3 fit equals
  L1's (`perms.json`) layer by layer: same classes, same order, same objective.

## 2. Where the relabelled channels go in L3

The fit decides each channel's class. The channels of class r, in increasing original
index, fill the positions p ≡ r (mod 4) in increasing order (`fit.order_from_group`, the
encoding `perms.json` uses), and channel order[p] of 3×3 position s then goes to slot
s·C + (p + s) mod C. Under the skewed rule the bank depends only on s and p mod 4, so
the order within a class changes no count.

## 3. L1 on B-32 ReLU s1: Frozen and Multi-start

PROTOCOL_2 defines L1 as `perms.json`'s fitted orders and, on B-32 ReLU s1, "also the
published Frozen and Multi-start layouts". On that network `perms.json`'s orders are
the published Frozen groups (H0 of PROTOCOL.md, exact match). The published Multi-start
groups (`research/q1_codesign/multistart_export_20261018.json`) are counted as an extra
layout, `L1_multistart`, with its summaries and interval. H5 uses `perms.json`'s L1
on every network, as the protocol's L1 definition does. L2 against Multi-start on B-32
ReLU s1 is reported beside H5 as context.

## 4. The bootstrap

PROTOCOL_2 asks for a paired bootstrap over images, 10,000 resamples, seed 0, 95%
percentile interval, for the pooled saving of L1, L2, L3 against L0 and for L3 − L2.
The reading taken:
- the 79 headline images (all but Set12 01.png), in sorted (set, image) order;
- one index matrix `np.random.default_rng(0).integers(0, 79, size=(10000, 79))`,
  drawn once and used for every network, width and layout, so every layout's resample
  holds the same images (paired), and L3 − L2 is the difference of the two pooled
  savings on the same resample (images resampled jointly);
- statistic: the pooled saving 100·(ΣL0 − Σlayout)/ΣL0 over the resampled images;
- interval: `np.percentile` at 2.5 and 97.5 (numpy's default linear interpolation).
At W = 1 (and wherever a layout cannot change the count) the interval is [0, 0].

## 5. The function-preservation check

PROTOCOL_2 says the integer-oracle accumulators were checked on every layer of 05.png
for every network and layout. Here, for L2 and L3 on every network: every window of
every layer of Set12 05.png (not a sample), `run_cifar.oracle`:
- L2: the skewed taps and weight columns give the original accumulators exactly;
- L3: the L3 relabeling is folded into an export with `fold.fold` (producer rows, bias,
  requant; both maps of a pooled channel), which is emulated with `run_denoise`; its
  windows are the original's relabelled, its accumulators the original's with the
  output columns permuted, and with the skew on its taps and weight columns the
  accumulators are still the original's up to that column order; its denoised image is
  identical; the windows counted for L3 are exactly the folded network's skewed windows.
L0 needs no check and L1 was checked by `fold_check.json` (PROTOCOL.md). The host
driver's own export path for L2 on B-32 ReLU s1 is a separate check, not part of
`evaluate_2.py`.

## 6. H4, H5, H6: which images and which networks

- H4 ("on every image") is checked on all 80 images, 01.png included, on the totals
  and also on every layer.
- "Networks with C mod 4 = 0" are those whose fitted layers all have C_in mod 4 = 0,
  read from `perms.json`; that is the nine other than 10 × 45.
- "Larger" is strict (>) on the pooled savings as floats; "the interval excludes 0"
  means lower bound > 0 or upper bound < 0.

## 7. How the run was carried out

The count is the same computation as `evaluate.py` (one host emulation of the original
network per image; every layout's windows are the original's with the fitted layers'
input columns permuted), cached per image so that a run cut short resumes where it
stopped. A cache entry carries a digest of the L1 and L3 orders it was counted with and
is ignored if they change. `results_2.json` is assembled from the cache only when all
800 image counts and 10 function checks are present.
