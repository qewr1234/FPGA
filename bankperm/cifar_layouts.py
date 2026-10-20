"""Beyond the denoisers: the four layouts L0-L3 on the CIFAR-10 classifier of cifar/ (a count, not a
board run, and NOT pre-registered).

    python bankperm/cifar_layouts.py --export EXPORT --test-npz TEST.npz      # or --data DIR
                                     [--images 10000] [--provenance P.json] [--out bankperm/cifar_layouts.json]

EXPORT is cifar/quantize_cifar.py's output for a network trained by cifar/train_cifar.py
(manifest.json + conv<N>_config.bin; six 3x3 convolutions 3-32-32-64-64-128-128, 2x2 max pool
after every second one, then global average pool and a 128x10 classifier on the host). The test
images are the CIFAR-10 test set, either the torchvision folder (--data DIR holding
cifar-10-batches-py, read by scripts/run_cifar.load_cifar_test) or an npz of the same images
(--test-npz: images uint8 (N, 3, 32, 32), labels). The network is run as the board driver runs
it in emulation (scripts/run_cifar.py main: im2col, oracle, requant, maxpool2, classify), in
batches of images.

Layouts (bankperm/PROTOCOL_2.md; only the inputs of the layers that read a hidden map change):

  L0  conventional: tap t = s*C + p (s the 3x3 position, p the channel), bank t % 4.
  L1  relabeling: fit.fit_general under the conventional rule (fit.py's recipe).
  L2  skew: channel p of position s in slot s*C + (p + s) % C (skew_count.skew_order).
  L3  skew + relabeling: fit.fit_general under the skewed rule (evaluate_2.skew_residue_counts),
      then skewed (evaluate_2.skew_columns).

Recipe of L1 and L3 (PROTOCOL.md / PROTOCOL_2.md, unchanged where it applies): one calibration
image (CIFAR-10 test image CALIB_INDEX, left out of the headline); its windows of every fitted
layer captured as the driver builds them; per fitted layer min(2048, windows) windows drawn
without replacement by ONE np.random.default_rng(42) in layer order; identity start, 400
proposals, generator seed 42 + fitted-layer index, objective the mean W=4 window cycles
(predict_w4.window_cycles; checked against fit.fast_cycles on the calibration windows, and for
C % 4 == 0 the search against q1_reviewer_bank.fit_group, as fit.py does).

Where this differs from the denoiser protocols (recorded in the output as `adaptations`):
  * fitted layers are conv2..conv6, i.e. every layer that reads a hidden map. The protocols' rule
    "conv2 .. conv(L-1)" left out the denoisers' output layer, where (2) holds (COUT <= 4); here
    the last convolution is a 128-channel hidden layer (GAP and the classifier run on the host),
    so it is fitted too. The totals with conv6 left at L0 are reported as well; they are exactly
    the strict reading (conv6 is the last fitted layer, so the window draws and seeds of conv2..
    conv5 do not depend on it);
  * a 32x32 image has 1024 / 256 / 256 / 64 / 64 windows at conv2..conv6, fewer than 2048, so
    the calibration sample is every window of the calibration image (fit.py's min(SAMPLE, len));
  * the counting run computes accumulators as float64 BLAS products (exact: every partial sum is
    an integer below K*127*128 < 2^31 < 2^53) and checks them against run_cifar.oracle on the
    first batch and on the function-check image.

The count: per image, sum over conv1..conv6 of predict_w4.window_cycles (sparse mode, P = 16,
T = 4, fill and drain left out) on the layout's windows at W = 1, 2, 4, and the per-window
perfect-balance bound max(ceil(K/W)+1, ceil(COUT/16)*max(1, ceil(nnz/4)), COUT) (baselines.py).
A layout's windows are the original's with the fitted layers' columns permuted (the activation
values are the same; L1/L3 fold the relabeling into the producer, checked below). On every
image and fitted layer the W=4 count of L1, L2 and L3 is also checked against the fits' fast
objective (as evaluate_2.count_image does). Headline: every test image other than the
calibration image; paired bootstrap over those images (10,000 resamples drawn from one
np.random.default_rng(0) in chunks of 1,000, 95% percentile interval) of the pooled saving of
L1, L2, L3 against L0 and of L3 - L2.

Function preservation (test image FCHECK_INDEX, every layer, all windows): run_cifar.oracle on
the layout's columns of windows and weights equals the original accumulators for L1, L2, L3;
L1 and L3 folded into the network (producer rows, bias, requant; consumer input taps) and
emulated: windows = the original's relabelled, accumulators = the original's up to the output
column order, the L3 count's windows = the folded network's skewed, logits and class identical.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
from evaluate_2 import check_bank_rule, skew_columns, skew_residue_counts  # noqa: E402
from fit import (SAMPLE, SEED, STEPS, fast_cycles, fit_general, group_from_order,  # noqa: E402
                 order_from_group, permuted_columns, residue_counts, write_json)
from predict_w4 import P, T, window_cycles  # noqa: E402
from q1_reviewer_bank import encode_order, fit_group  # noqa: E402
from run_cifar import QMAX_A, classify, im2col, load_cifar_test, maxpool2, oracle, requant  # noqa: E402
from skew_count import skew_order  # noqa: E402

WIDTHS = (1, 2, 4)
LAYOUTS = ('L0', 'L1', 'L2', 'L3')
COLS = LAYOUTS + ('perfect_balance',)
CALIB_INDEX, FCHECK_INDEX = 0, 1
N_BOOT, BOOT_SEED, BOOT_CHUNK = 10_000, 0, 1_000
BATCH = 100


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- the network

def load_export(export):
    man = json.loads((export/'manifest.json').read_text())
    layers = []
    for L in man['layers']:
        blob = np.frombuffer((export/L['config']).read_bytes(), '<i4')
        k, cout = L['K'], L['COUT']
        assert blob.size == cout*k + cout, L['name']
        wq = blob[:cout*k].reshape(cout, k)
        assert wq.min() >= -128 and wq.max() <= 127, L['name']
        layers.append(dict(name=L['name'], K=k, COUT=cout, pool_after=bool(L['pool_after']),
                           requant=np.asarray(L['requant'], np.float64), wq=wq.astype(np.int8),
                           bq=blob[cout*k:].astype(np.int32), kh=3, kw=3))
    return man, layers


def exact_acc(x, wq, bq):
    """run_cifar.oracle's ReLU(bias + x W^T) in INT32, as a float64 BLAS product (exact, see the docstring)."""
    y = x.astype(np.float64) @ wq.astype(np.float64).T + bq.astype(np.float64)
    y = np.maximum(0.0, y)
    if y.max() > 2**31 - 1:
        raise SystemExit('accumulator overflows INT32')
    return y.astype(np.int32)


def emulate(images, man, layers, hook=None, acc_fn=exact_acc):
    """scripts/run_cifar.py main's emulation path on a batch of images (float in [0, 1]).
    hook(i, L, x, acc) sees every layer's windows and accumulators. -> (final map, classes)."""
    a0 = man['layers'][0]['a_scale_in']
    q = np.clip(np.rint(images/a0), 0, QMAX_A).astype(np.uint8)
    for i, L in enumerate(layers):
        b, c, h, w = q.shape
        x = im2col(q)
        assert x.shape[1] == L['K'], L['name']
        acc = acc_fn(x, L['wq'], L['bq'])
        if hook is not None:
            hook(i, L, x, acc)
        nxt = requant(acc, L['requant'])
        q = nxt.reshape(b, h, w, L['COUT']).transpose(0, 3, 1, 2)
        if L['pool_after']:
            q = maxpool2(q)
        q = np.ascontiguousarray(q)
    return q, classify(q, man)


def fitted_indices(layers):
    """Every layer that reads a hidden map: conv2 .. conv6 (see the docstring)."""
    return list(range(1, len(layers)))


def taps_cin(L):
    cin, r = divmod(L['K'], 9)
    assert r == 0
    return 9, cin


def condition_2(layers):
    """bounds.py's rule per layer: a layout can change the count only if (2) fails."""
    rows = []
    for L in layers:
        k, cout = L['K'], L['COUT']
        top = math.ceil(cout/P)*math.ceil(k/T)
        row = dict(name=L['name'], K=k, COUT=cout, C_in=k//9, max_compute=top)
        for w in WIDTHS:
            row[f'floor_w{w}'] = max(math.ceil(k/w) + 1, cout)
            row[f'can_gain_w{w}'] = bool(top > row[f'floor_w{w}'])
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------- 1. the fits

def fit_layouts(img, man, layers, fit_idx):
    wins = {}
    emulate(img[None], man, layers, lambda i, L, x, acc: wins.__setitem__(i, x.copy()) if i in fit_idx else None)
    rng = np.random.default_rng(SEED)                      # one generator, consumed in layer order
    rows, cols = [], {}
    for j, i in enumerate(fit_idx):
        L = layers[i]
        k, cout = L['K'], L['COUT']
        taps, cin = taps_cin(L)
        assert cin % T == 0, (L['name'], cin)
        x = wins[i]
        sel = rng.choice(len(x), size=min(SAMPLE, len(x)), replace=False)
        xs = x[sel]
        n0 = residue_counts(xs, taps, cin)
        ns = skew_residue_counts(xs, taps, cin)
        g1, best1, acc1 = fit_general(n0, k, cout, SEED + j, STEPS)
        g3, best3, acc3 = fit_general(ns, k, cout, SEED + j, STEPS)
        # fit.py: for C % 4 == 0 the search is q1_reviewer_bank.fit_group itself.
        assert not n0[:, :, 1:].any()
        g_ref, best_ref = fit_group(n0[:, :, 0], cout, k, SEED + j, STEPS)
        assert np.array_equal(g_ref, g1) and best_ref == best1, L['name']
        o1, o3 = order_from_group(g1), order_from_group(g3)
        assert np.array_equal(o1, encode_order(g_ref))
        assert np.array_equal(group_from_order(o1), g1) and np.array_equal(group_from_order(o3), g3)
        ident = np.arange(cin)
        c = dict(L0=np.arange(k), L1=permuted_columns(o1, taps), L2=skew_order(k, cin), L3=skew_columns(o3, taps))
        assert np.array_equal(skew_columns(ident, taps), c['L2'])
        assert check_bank_rule(c['L2'], ident % T, taps) and check_bank_rule(c['L3'], g3, taps)
        # The objectives are predict_w4.window_cycles on the permuted windows (fit.py, evaluate_2.py).
        control = np.random.default_rng(1000 + j).permutation(cin)
        for o in (ident, o1, o3, control):
            for n, colf in ((n0, permuted_columns), (ns, skew_columns)):
                cc = colf(o, taps)
                for w in WIDTHS:
                    if not np.array_equal(window_cycles(xs[:, cc], k, cout, w),
                                          fast_cycles(n, group_from_order(o), k, cout, w)):
                        raise AssertionError(f'{L["name"]} W={w}: fast objective differs from window_cycles')
        means = {lay: float(np.mean(window_cycles(xs[:, c[lay]], k, cout, 4))) for lay in LAYOUTS}
        assert means['L1'] == best1 and means['L3'] == best3
        cols[i] = dict(cols=c, taps=taps, cin=cin, g1=g1, g3=g3, o1=o1, o3=o3)
        rows.append(dict(layer=L['name'], producer=layers[i-1]['name'], C_in=cin, K=k, COUT=cout, seed=SEED + j,
                         calibration_windows=int(len(sel)), of_windows=int(len(x)),
                         cal_mean_w4={lay: means[lay] for lay in LAYOUTS},
                         cal_saving_w4_pct={lay: 100*(means['L0'] - means[lay])/means['L0'] for lay in LAYOUTS[1:]},
                         accepted_swaps=dict(L1=acc1, L3=acc3),
                         class_sizes=dict(L1=[int((g1 == r).sum()) for r in range(T)],
                                          L3=[int((g3 == r).sum()) for r in range(T)]),
                         channels_L3_in_another_class_than_L1=int((g1 != g3).sum()),
                         order_L1=o1.tolist(), order_L3=o3.tolist()))
    return rows, cols


# ----------------------------------------------------------------------------- 2. the count

def count_all(images, man, layers, lay, fit_idx, check_batches):
    """-> per image, layer, column (L0..L3, perfect balance) and width: summed window cycles."""
    n = len(images)
    tot = np.zeros((n, len(layers), len(COLS), len(WIDTHS)), np.int64)
    preds = np.empty(n, np.int64)
    checked = dict(oracle_batches=0, fast_objective_batches=0)
    for b0 in range(0, n, BATCH):
        xb = images[b0:b0 + BATCH]
        nb = len(xb)
        first = b0 < check_batches*BATCH

        def hook(i, L, x, acc):
            k, cout = L['K'], L['COUT']
            if first and not np.array_equal(oracle(x, L['wq'], L['bq']), acc):
                raise AssertionError(f'{L["name"]}: float64 accumulators differ from run_cifar.oracle')
            per = x.shape[0]//nb
            nnz = (x != 0).sum(1)
            g = math.ceil(cout/P)
            for wi, w in enumerate(WIDTHS):
                pb = np.maximum(np.maximum(math.ceil(k/w) + 1, g*np.maximum(-(-nnz//T), 1)), cout)
                tot[b0:b0+nb, i, 4, wi] = pb.reshape(nb, per).sum(1)
            if i not in fit_idx:
                for wi, w in enumerate(WIDTHS):
                    tot[b0:b0+nb, i, :4, wi] = window_cycles(x, k, cout, w).reshape(nb, per).sum(1)[:, None]
                assert (tot[b0:b0+nb, i, 4] <= tot[b0:b0+nb, i, 0]).all(), 'L0 below perfect balance'
                return
            r = lay[i]
            got = {}
            for li, name in enumerate(LAYOUTS):
                xp = x[:, r['cols'][name]] if name != 'L0' else x
                for wi, w in enumerate(WIDTHS):
                    c = window_cycles(xp, k, cout, w)
                    if w == 4:
                        got[name] = c
                    tot[b0:b0+nb, i, li, wi] = c.reshape(nb, per).sum(1)
            if first:   # evaluate_2.count_image's check: the W=4 count is the fits' fast objective
                n0 = residue_counts(x, r['taps'], r['cin'])
                ns = skew_residue_counts(x, r['taps'], r['cin'])
                for name, res, grp in (('L1', n0, r['g1']), ('L2', ns, np.arange(r['cin']) % T), ('L3', ns, r['g3'])):
                    if not np.array_equal(got[name], fast_cycles(res, grp, k, cout, 4)):
                        raise AssertionError(f'{L["name"]} {name}: fast objective != window_cycles')
            assert (tot[b0:b0+nb, i, 4] <= tot[b0:b0+nb, i, :4].min(1)).all(), 'a layout below perfect balance'

        _, p = emulate(xb, man, layers, hook)
        preds[b0:b0+nb] = p
        if first:
            checked['oracle_batches'] += 1
            checked['fast_objective_batches'] += 1
        if (b0//BATCH) % 10 == 0:
            print(f'  counted {b0 + nb}/{n} images', flush=True)
    checked['images_checked'] = min(n, check_batches*BATCH)
    return tot, preds, checked


# ----------------------------------------------------------------------------- 3. function preservation

def fold(layers, lay, which):
    """L1 or L3's relabeling folded into a copy of the network: producer rows, bias and requant
    factor in the new channel order, consumer input taps likewise. -> (layers, output order per layer)."""
    out = [dict(L) for L in layers]
    pout = {i: np.arange(L['COUT']) for i, L in enumerate(layers)}
    for i, r in lay.items():
        o = r['o1'] if which == 'L1' else r['o3']
        p = out[i-1]
        p['wq'], p['bq'], p['requant'] = p['wq'][o], p['bq'][o], p['requant'][o]
        pout[i-1] = o
        c = out[i]
        c['wq'] = c['wq'][:, permuted_columns(o, r['taps'])]
    return out, pout


def function_check(img, man, layers, lay, fit_idx):
    ref = {}
    q0, p0 = emulate(img[None], man, layers, lambda i, L, x, acc: ref.__setitem__(i, (x.copy(), acc.copy())),
                     acc_fn=oracle)
    rows = []
    for i, L in enumerate(layers):
        x, acc = ref[i]
        row = dict(layer=L['name'], windows=int(x.shape[0]), fitted=i in fit_idx,
                   float64_path_equals_oracle=bool(np.array_equal(exact_acc(x, L['wq'], L['bq']), acc)))
        for name in LAYOUTS[1:]:
            c = lay[i]['cols'][name] if i in fit_idx else np.arange(L['K'])
            row[f'{name}_taps_and_weight_columns_accumulators_equal'] = bool(
                np.array_equal(oracle(x[:, c], L['wq'][:, c], L['bq']), acc))
        rows.append(row)
    folded = {}
    for which in ('L1', 'L3'):
        fl, pout = fold(layers, lay, which)
        got = {}
        q1, p1 = emulate(img[None], man, fl, lambda i, L, x, acc: got.__setitem__(i, (x.copy(), acc.copy())),
                         acc_fn=oracle)
        for i, L in enumerate(fl):
            x0, a0 = ref[i]
            x1, a1 = got[i]
            row = rows[i]
            if i in fit_idx:
                r = lay[i]
                o = r['o1'] if which == 'L1' else r['o3']
                row[f'{which}_folded_windows_are_relabelled_original'] = bool(
                    np.array_equal(x1, x0[:, permuted_columns(o, r['taps'])]))
                if which == 'L3':
                    sk = skew_order(L['K'], r['cin'])
                    row['L3_counted_windows_are_folded_skewed'] = bool(np.array_equal(x1[:, sk], x0[:, r['cols']['L3']]))
                    row['L3_folded_skewed_accumulators_equal_up_to_column_order'] = bool(
                        np.array_equal(oracle(x1[:, sk], L['wq'][:, sk], L['bq']), a0[:, pout[i]]))
            row[f'{which}_folded_accumulators_equal_up_to_column_order'] = bool(np.array_equal(a1, a0[:, pout[i]]))
        folded[which] = dict(final_map_identical=bool(np.array_equal(q0, q1)), class_identical=bool(p0[0] == p1[0]))
    flags = [v for r in rows for k, v in r.items() if isinstance(v, bool) and k != 'fitted']
    flags += [v for d in folded.values() for v in d.values()]
    return dict(image=f'CIFAR-10 test image {FCHECK_INDEX}', oracle='scripts/run_cifar.oracle on every window of '
                'every layer', layers=rows, folded=folded, all_ok=bool(all(flags)))


# ----------------------------------------------------------------------------- 4. results

def saving(o, p):
    return 100*(np.asarray(o, np.float64) - p)/o


def ci(v):
    lo, hi = np.percentile(v, [2.5, 97.5])
    return [float(lo), float(hi)]


def summarize(tot, head, calib, layers, fit_idx, cond):
    """Per width: pooled savings over the headline images, paired bootstrap, per-layer and per-image detail."""
    th = tot[head]                                                         # (n, layer, column, width)
    n, last = len(head), len(layers) - 1
    boot_rng = np.random.default_rng(BOOT_SEED)
    sums = {}
    for wi, w in enumerate(WIDTHS):
        img = th[:, :, :, wi].sum(1)                                       # (n, column)
        strict = img - th[:, last, :, wi] + th[:, last, 0:1, wi]           # conv6 left at L0
        sums[w] = (img, strict)
    names = ('L1', 'L2', 'L3', 'perfect_balance', 'L1_strict', 'L2_strict', 'L3_strict')
    boots = {w: {k: [] for k in names} for w in WIDTHS}
    for _ in range(N_BOOT//BOOT_CHUNK):
        idx = boot_rng.integers(0, n, size=(BOOT_CHUNK, n))
        for w in WIDTHS:
            img, strict = sums[w]
            so = img[:, 0][idx].sum(1).astype(np.float64)
            for c, name in enumerate(COLS[1:], 1):
                boots[w][name].append(100*(so - img[:, c][idx].sum(1))/so)
            for c, name in enumerate(LAYOUTS[1:], 1):
                boots[w][f'{name}_strict'].append(100*(so - strict[:, c][idx].sum(1))/so)
    boots = {w: {k: np.concatenate(v) for k, v in b.items()} for w, b in boots.items()}
    per_w = {}
    for wi, w in enumerate(WIDTHS):
        img, strict = sums[w]
        o, pb = img[:, 0], img[:, 4]
        layer_l0 = {layers[i]['name']: int(th[:, i, 0, wi].sum()) for i in range(len(layers))}
        rec = dict(L0_cycles=int(o.sum()), L0_cycles_per_image=float(o.mean()),
                   L0_share_of_cycles_per_layer_pct={k: 100*v/o.sum() for k, v in layer_l0.items()},
                   perfect_balance=dict(
                       cycles=int(pb.sum()), pooled_pct=float(saving(o.sum(), pb.sum())),
                       bootstrap_95_pct=ci(boots[w]['perfect_balance']),
                       per_layer_pooled_pct={layers[i]['name']: float(saving(th[:, i, 0, wi].sum(), th[:, i, 4, wi].sum()))
                                             for i in fit_idx}))
        for c, name in enumerate(LAYOUTS[1:], 1):
            p = img[:, c]
            s = saving(o, p)
            worse = int(sum((th[:, i, c, wi] > th[:, i, 0, wi]).sum() for i in fit_idx))
            better = int(sum((th[:, i, c, wi] < th[:, i, 0, wi]).sum() for i in fit_idx))
            a, b = int(tot[calib, :, 0, wi].sum()), int(tot[calib, :, c, wi].sum())
            rec[name] = dict(
                pooled_pct=float(saving(o.sum(), p.sum())), bootstrap_95_pct=ci(boots[w][name]),
                layout_cycles=int(p.sum()), min_pct=float(s.min()), median_pct=float(np.median(s)),
                max_pct=float(s.max()), images_saving_lt_0=int((s < 0).sum()), images_saving_eq_0=int((s == 0).sum()),
                image_layers=n*len(fit_idx), image_layers_worse_than_L0=worse, image_layers_better_than_L0=better,
                share_of_perfect_balance_saving_pct=(float(100*(o.sum() - p.sum())/(o.sum() - pb.sum()))
                                                     if pb.sum() < o.sum() else None),
                per_layer_pooled_pct={layers[i]['name']: float(saving(th[:, i, 0, wi].sum(), th[:, i, c, wi].sum()))
                                      for i in fit_idx},
                conv6_left_at_L0=dict(pooled_pct=float(saving(o.sum(), strict[:, c].sum())),
                                      bootstrap_95_pct=ci(boots[w][f'{name}_strict'])),
                calibration_image=dict(L0=a, layout=b, saving_pct=float(saving(a, b))))
        d = saving(o, img[:, 3]) - saving(o, img[:, 2])
        rec['L3_minus_L2'] = dict(
            pooled_pct_points=rec['L3']['pooled_pct'] - rec['L2']['pooled_pct'],
            bootstrap_95_pct_points=ci(boots[w]['L3'] - boots[w]['L2']),
            per_image_min=float(d.min()), per_image_median=float(np.median(d)), per_image_max=float(d.max()),
            images_L3_below_L2=int((img[:, 3] < img[:, 2]).sum()), images_L3_above_L2=int((img[:, 3] > img[:, 2]).sum()))
        rec['L2_minus_L1'] = dict(pooled_pct_points=rec['L2']['pooled_pct'] - rec['L1']['pooled_pct'],
                                  bootstrap_95_pct_points=ci(boots[w]['L2'] - boots[w]['L1']))
        can = [layers[i]['name'] for i in fit_idx if cond[i][f'can_gain_w{w}']]
        # (2) must hold exactly: where it holds, the layer counts as L0 under every layout on every image (all n + 1).
        zero_ok = all((tot[:, i, c, wi] == tot[:, i, 0, wi]).all() for i in fit_idx for c in (1, 2, 3)
                      if layers[i]['name'] not in can)
        rec['condition_2'] = dict(fitted_layers_that_can_gain=can, others_count_as_L0_on_every_image=bool(zero_ok))
        per_w[f'w{w}'] = rec
    return per_w


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--export', type=Path, required=True, help='cifar/quantize_cifar.py output')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--data', type=Path, help='folder holding cifar-10-batches-py (run_cifar.load_cifar_test)')
    src.add_argument('--test-npz', type=Path, help='npz: images uint8 (N, 3, 32, 32), labels')
    ap.add_argument('--images', type=int, default=10_000)
    ap.add_argument('--check-batches', type=int, default=1, help='batches checked against oracle / fast objective')
    ap.add_argument('--provenance', type=Path, help='JSON describing how the export was made (copied in)')
    ap.add_argument('--no-per-image', action='store_true')
    ap.add_argument('--out', type=Path, default=HERE/'cifar_layouts.json')
    args = ap.parse_args()
    t0 = time.time()

    man, layers = load_export(args.export)
    if args.data:
        images, labels = load_cifar_test(args.data, args.images)
        source = dict(kind='cifar-10-batches-py/test_batch (run_cifar.load_cifar_test)',
                      sha256=sha256(args.data/'cifar-10-batches-py'/'test_batch'))
    else:
        d = np.load(args.test_npz)
        images = d['images'][:args.images].astype(np.float64)/255.0
        labels = d['labels'][:args.images].astype(np.int64)
        source = dict(kind='npz of the CIFAR-10 test set, images uint8 (N, 3, 32, 32) / 255 as run_cifar.load_cifar_test',
                      sha256=sha256(args.test_npz))
    assert images.shape[1:] == (3, 32, 32)
    n = len(images)
    fit_idx = fitted_indices(layers)
    cond = condition_2(layers)
    print(f'{n} test images; layers ' + ', '.join(f'{L["name"]} K={L["K"]} COUT={L["COUT"]}' for L in layers))

    rows, lay = fit_layouts(images[CALIB_INDEX], man, layers, fit_idx)
    for r in rows:
        print(f'  fit {r["layer"]:<6} C_in={r["C_in"]:<4} {r["calibration_windows"]:>5} windows   calibration W=4 saving '
              + '  '.join(f'{k} {v:6.2f}%' for k, v in r['cal_saving_w4_pct'].items()), flush=True)
    fc = function_check(images[FCHECK_INDEX], man, layers, lay, fit_idx)
    print('function check', 'ok' if fc['all_ok'] else 'FAILED', flush=True)
    assert fc['all_ok']

    tot, preds, checked = count_all(images, man, layers, lay, fit_idx, args.check_batches)
    head = np.array([i for i in range(n) if i != CALIB_INDEX])
    summary = summarize(tot, head, CALIB_INDEX, layers, fit_idx, cond)
    acc_all = float((preds == labels).mean())
    acc_head = float((preds[head] == labels[head]).mean())

    out = dict(
        what='count, not a board measurement, and NOT pre-registered: layouts L0-L3 (PROTOCOL_2.md) on the CIFAR-10 '
             'classifier of cifar/ (train_cifar.py, quantize_cifar.py), per-window predict_w4.window_cycles, '
             'sparse mode, conv1..conv6, fill and drain left out',
        network=dict(convs=man['convs'], layers=[dict(name=L['name'], K=L['K'], COUT=L['COUT'],
                                                      pool_after=L['pool_after']) for L in layers],
                     float_accuracy_from_manifest=man['float_accuracy'],
                     integer_accuracy_all_test_images=acc_all, integer_accuracy_headline_images=acc_head,
                     integer_accuracy_note='scripts/run_cifar.py emulation path (classify), on the images below',
                     export_files_sha256={p.name: sha256(p) for p in sorted(args.export.iterdir()) if p.is_file()}),
        provenance=json.loads(args.provenance.read_text()) if args.provenance else None,
        images=dict(source=source, count=n, calibration_image=f'test index {CALIB_INDEX}',
                    function_check_image=f'test index {FCHECK_INDEX}',
                    headline=f'the {len(head)} test images other than the calibration image'),
        layouts=dict(L0='conventional, bank (s*C + p) % 4', L1='fit.fit_general under the conventional rule',
                     L2='skew_count.skew_order: slot s*C + (p + s) % C, bank (s + p) % 4',
                     L3='fit.fit_general under the skewed rule (evaluate_2.skew_residue_counts), then '
                        'evaluate_2.skew_columns'),
        recipe=dict(windows_per_layer=f'min({SAMPLE}, windows of the calibration image)',
                    window_generator=f'one np.random.default_rng({SEED}), layer order',
                    search=f'fit.fit_general: identity start, {STEPS} proposals, seed {SEED} + fitted-layer index',
                    objective='mean W=4 window cycles'),
        adaptations=[
            'network and images: the CIFAR-10 classifier and the CIFAR-10 test set, not the denoisers on Set12/BSD68; '
            f'calibration image = test image {CALIB_INDEX} (in place of Set12 01.png)',
            'fitted layers conv2..conv6 (every layer reading a hidden map), conv6 included because its COUT is 128 '
            '(the protocols left out the denoisers\' COUT <= 4 output layer); conv6_left_at_L0 gives the strict reading',
            'calibration sample = every window of the 32x32 calibration image (1024/256/256/64/64 < 2048)',
            'counting run: accumulators as an exact float64 product, checked against run_cifar.oracle '
            f'on the first {checked["images_checked"]} images and on the function-check image'],
        condition_2=cond, fit=rows, function_check=fc, checks=dict(
            **checked, perfect_balance_le_every_layout_every_image_layer=True,
            note='asserted while counting: float64 accumulators == run_cifar.oracle and the W=4 count == the fits\' '
                 'fast objective on the checked images; perfect balance <= every layout on every image and layer'),
        bootstrap=dict(resamples=N_BOOT, generator=f'np.random.default_rng({BOOT_SEED}).integers(0, {len(head)}, '
                       f'({BOOT_CHUNK}, {len(head)})) x {N_BOOT//BOOT_CHUNK}, paired over layouts and widths',
                       interval='95% percentile'),
        saving='100 * (L0 - layout) / L0, pooled = on the summed counts of the headline images',
        summary=summary, seconds=round(time.time() - t0, 1))
    if not args.no_per_image:
        out['per_image_totals'] = dict(
            order=f'per_image_totals[wN][column][image], column in {list(COLS)}, image = test index',
            **{f'w{w}': {c: tot[:, :, ci_, wi].sum(1).tolist() for ci_, c in enumerate(COLS)}
               for wi, w in enumerate(WIDTHS)})
        out['per_image_class'] = preds.tolist()
    write_json(args.out, out)

    print(f'\ninteger accuracy {acc_all*100:.2f}% on {n} images (float {man["float_accuracy"]*100:.2f}%)')
    for w in WIDTHS:
        s = summary[f'w{w}']
        print(f'W={w}: ' + '  '.join(f'{k} {s[k]["pooled_pct"]:6.2f}% [{s[k]["bootstrap_95_pct"][0]:.2f}, '
                                    f'{s[k]["bootstrap_95_pct"][1]:.2f}]' for k in ('L1', 'L2', 'L3', 'perfect_balance'))
              + f'  L3-L2 {s["L3_minus_L2"]["pooled_pct_points"]:.2f} {s["L3_minus_L2"]["bootstrap_95_pct_points"]}'
              + f'  can gain: {s["condition_2"]["fitted_layers_that_can_gain"]}')
    print('wrote', args.out, f'({time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
