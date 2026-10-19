"""PROTOCOL_2.md: the skewed layout (L2) and skew + relabeling (L3) against L0 and L1, on every network.

    python bankperm/evaluate_2.py --cache DIR [--jobs 2] [--networks A,B...] [--no-assemble]
        # 1. fits L3 into bankperm/perms_2.json (if it is not there yet; about 2 minutes)
        # 2. counts all 80 images of every network, one cached JSON per image in DIR
        # 3. checks function preservation on Set12 05.png, one cached JSON per network in DIR
        # 4. when every network is cached: bankperm/results_2.json
    Every step is resumable: a rerun with the same --cache only does what is not cached yet.

Layouts (bankperm/PROTOCOL_2.md; only the inputs of conv2 .. conv(L-1) change):

  L0  conventional: tap t = s*C + p (s the 3x3 position, p the channel position), bank t % 4.
  L1  relabeling: the fitted orders of PROTOCOL.md (bankperm/perms.json `orders`); on
      B-32 ReLU s1 also the published Multi-start layout, as context (perms.json's order
      there is the published Frozen one, H0).
  L2  skew: channel p of position s in slot s*C + (p + s) % C, bank (s + p) % 4, for
      C % 4 == 0 (skew_count.skew_order); for C % 4 == 1 (10 x 45) the conventional slot
      s*C + p already has bank (s + p) % 4, so L2 = L0 there.
  L3  skew + relabeling: the channels' position classes refitted under the skewed bank
      rule, bank = (s + class) % 4, with the PROTOCOL.md recipe (fit.fit_general: identity
      start, 400 proposals, Set12 01.png, 2048 windows per fitted layer from one
      np.random.default_rng(42) in layer order, generator seed 42 + fitted-layer index,
      objective the mean W=4 window cycles). The fitted order (position -> original
      channel, fit.order_from_group) is then skewed: slot s*C + (p + s) % C reads original
      channel order[p]. For 10 x 45 the skewed rule is its conventional rule: L3 = L1.

The count (as evaluate.py): all 80 test images (Set12 + BSD68, sigma 25, test_noise seed 0),
the board driver's host emulation (scripts/run_denoise.py) of the original network, and
per image the per-window predict_w4.window_cycles (sparse mode) summed over conv1-convL at
W = 1, 2, 4. A layout's windows are the original's with the input columns of the fitted
layers permuted: a layout permutes taps and weight columns together (and L1/L3 fold the
relabeling into the producer), so the activation values are the same, only their slots
move. On every image and fitted layer the W=4 count of L1, L2 and L3 is also checked
against fit.py's fast objective (the one the fits minimise).

Function preservation (Set12 05.png, every network, every layer, all windows, the integer
oracle run_cifar.oracle): L2 -- oracle(x[:, c], W[:, c], b) == the original accumulators,
c the skewed columns; L3 -- the L3 relabeling folded into an export (fold.fold: producer
rows, bias, requant, both maps of a pooled channel; consumer input taps), emulated: its
windows are the original's relabelled, its accumulators the original's with the output
columns permuted, and with the skew on its taps and weight columns
(oracle(x1[:, c], W1[:, c], b1)) the accumulators are still the original's up to that
column order; its denoised image is the original's.

results_2.json: per network, layout and width the per-image totals; over the 79 images
other than Set12 01.png the pooled saving vs L0, per-image min/median/max, images with
saving <= 0 and image-layers worse than L0; the paired bootstrap 95% intervals (10,000
resamples of the 79 images, np.random.default_rng(0), percentile) of the pooled saving of
L1, L2, L3 vs L0 and of L3 - L2; the cross-checks (asserted); the verdicts H4-H6.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from count_test_sets import MODELS, SETS  # noqa: E402
from predict_w4 import T, window_cycles  # noqa: E402
from run_cifar import oracle  # noqa: E402
from fit import (CALIB, SAMPLE, SEED, STEPS, emulate, export_dir, fast_cycles, fit_general,  # noqa: E402
                 fitted_layers, group_from_order, noisy_input, order_from_group, permuted_columns,
                 residue_counts, taps_and_channels, write_json)
from fold import fold, window_columns  # noqa: E402
from skew_count import skew_order  # noqa: E402

WIDTHS = (1, 2, 4)
SIGMA = 25
ALSO = ('Set12', '05.png')
LAYOUTS = ('L0', 'L1', 'L2', 'L3')
MS_LABEL = 'B-32 ReLU + QAT s1'                          # the network with published Frozen/Multi-start layouts
MS = 'L1_multistart'
MULTI_JSON = ROOT/'research'/'q1_codesign'/'multistart_export_20261018.json'
B32_TESTSETS = HERE/'b32_testsets.json'
N_BOOT, BOOT_SEED = 10_000, 0
PERMS_2 = HERE/'perms_2.json'
_STATE = {}


# ----------------------------------------------------------------------------- layouts

def skew_residue_counts(x, taps, cin):
    """(N, K) windows -> (N, C_in, 4) uint8: per window and channel, the nonzero taps at 3x3
    positions s with s % 4 == a. Under the skewed rule a channel of class r has its tap at
    position s in bank (s + r) % 4, so fit.bank_counts / fast_cycles apply unchanged."""
    nz = (x != 0).reshape(len(x), taps, cin)
    res = np.arange(taps) % T
    n = np.zeros((len(x), cin, T), np.uint8)
    for a in range(T):
        n[:, :, a] = nz[:, res == a, :].sum(1)
    return n


def skew_columns(order, taps):
    """Window columns of the skewed layout of a relabeling: slot s*C + (p + s) % C reads original
    column s*C + order[p] (C % 4 == 0). For C % 4 == 1 the conventional slot s*C + p already has
    bank (s + p) % 4: the columns are those of the relabeling alone."""
    order = np.asarray(order, np.int64)
    c = len(order)
    if c % T == 1:
        return permuted_columns(order, taps)
    if c % T != 0:
        raise SystemExit(f'no skewed layout defined for C_in = {c}')
    cols = np.empty(taps*c, np.int64)
    for s in range(taps):
        cols[s*c + (np.arange(c) + s) % c] = s*c + order
    return cols


def check_bank_rule(cols, group, taps):
    """Every slot's bank (slot % 4) is (s + class of the channel it reads) % 4."""
    c = len(group)
    s, ch = np.divmod(cols, c)
    return bool(np.array_equal(np.arange(taps*c) % T, (s + np.asarray(group)[ch]) % T))


def multistart_orders(layers):
    """The published Multi-start layout of B-32 ReLU s1, keyed by producer like perms.json."""
    by_name = {L['name']: L for L in layers}
    rows = json.loads(MULTI_JSON.read_text())['layers']
    return {by_name[r['layer']]['inputs'][0]: order_from_group(r['group_of_original_channel']).tolist()
            for r in rows}


# ----------------------------------------------------------------------------- 1. the L3 fit

def fit_network_2(label, model, perms1):
    """fit.fit_network's recipe with the skewed bank rule: the same windows, generator, search."""
    t0 = time.time()
    man, layers = run_denoise.load_layers(export_dir(model))
    fit = fitted_layers(layers)
    names = {L['name'] for L in fit}
    wins = {}

    def keep(L, x, acc):
        if L['name'] in names:
            wins[L['name']] = x.copy()

    emulate(man, layers, noisy_input(*CALIB, man['sigma'])[0], keep)
    rng = np.random.default_rng(SEED)                      # one generator, consumed in layer order
    rows1 = {r['layer']: r for r in perms1['fitted']}
    rows, orders = [], {}
    for i, L in enumerate(fit):
        k, cout = L['K'], L['COUT']
        taps, cin = taps_and_channels(L)
        x = wins[L['name']]
        sel = rng.choice(len(x), size=min(SAMPLE, len(x)), replace=False)
        xs = x[sel]
        n = skew_residue_counts(xs, taps, cin)
        group, best, accepted = fit_general(n, k, cout, SEED + i, STEPS)
        order = order_from_group(group)
        assert np.array_equal(group_from_order(order), group)
        identity = np.arange(cin) % T
        before = float(np.mean(fast_cycles(n, identity, k, cout, 4)))          # L2 on the calibration windows
        # The calibration windows are fit.py's: L0 and L1 under the conventional rule give perms.json's means.
        n0 = residue_counts(xs, taps, cin)
        r1 = rows1[L['name']]
        g1 = np.asarray(r1['class_of_original_channel'])
        l0 = float(np.mean(fast_cycles(n0, identity, k, cout, 4)))
        l1 = float(np.mean(fast_cycles(n0, g1, k, cout, 4)))
        if not (l0 == r1['cal_mean_before'] and l1 == r1['cal_mean_after'] and r1['seed'] == SEED + i):
            raise AssertionError(f'{label} {L["name"]}: calibration windows differ from fit.py\'s')
        # The objective is predict_w4.window_cycles on the skewed (and relabelled) windows.
        control = np.random.default_rng(1000 + i).permutation(cin)
        for o in (np.arange(cin), order, control):
            cols = skew_columns(o, taps)
            assert check_bank_rule(cols, group_from_order(o), taps)
            for w in WIDTHS:
                if not np.array_equal(window_cycles(xs[:, cols], k, cout, w),
                                      fast_cycles(n, group_from_order(o), k, cout, w)):
                    raise AssertionError(f'{label} {L["name"]} W={w}: fast objective differs from window_cycles')
        if cin % T == 0:
            assert np.array_equal(skew_columns(np.arange(cin), taps), skew_order(k, cin))
        else:   # 10 x 45: the skewed rule is the conventional rule, so the fit is L1's
            assert np.array_equal(n, n0)
            if not (order.tolist() == r1['order'] and group.tolist() == r1['class_of_original_channel']
                    and best == r1['cal_mean_after']):
                raise AssertionError(f'{label} {L["name"]}: L3 differs from L1 on a C % 4 == 1 layer')
        producer = L['inputs'][0]
        orders[producer] = order.tolist()
        rows.append(dict(layer=L['name'], producer=producer, C_in=cin, K=k, COUT=cout, seed=SEED + i,
                         calibration_windows=int(len(sel)), of_windows=int(len(x)),
                         class_sizes=[int((group == r).sum()) for r in range(T)],
                         cal_mean_L0=l0, cal_mean_L1=l1, cal_mean_L2=before, cal_mean_L3=best,
                         cal_saving_L3_vs_L2_pct=100*(before - best)/before,
                         cal_saving_L3_vs_L0_pct=100*(l0 - best)/l0, accepted_swaps=accepted,
                         channels_in_another_class_than_L1=int((group != g1).sum()),
                         order=order.tolist(), class_of_original_channel=group.tolist()))
    return dict(model=model, sigma=man['sigma'], fitted=rows, orders=orders,
                L3_equals_L1=all(r['channels_in_another_class_than_L1'] == 0 for r in rows),
                seconds=round(time.time() - t0, 1))


def fit_all(labels, jobs):
    perms1 = json.loads((HERE/'perms.json').read_text())['networks']
    out = dict(protocol='bankperm/PROTOCOL_2.md (L3)', recipe=dict(
        calibration=f'{CALIB[0]} {CALIB[1]}, sigma of the network, test_noise seed 0, host emulation',
        windows_per_layer=SAMPLE, window_generator=f'one np.random.default_rng({SEED}) per network, layer order '
                                                   '(the windows of perms.json, checked)',
        objective='mean W=4 window cycles, max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT), '
                  'under the skewed bank rule',
        search=f'bankperm/fit.py fit_general: identity start, {STEPS} swaps of channels in different classes, '
               f'accept if the objective falls by > 1e-10, seed {SEED} + fitted-layer index',
        bank_of_tap='(s + class) % 4, class = p % 4 of the channel\'s position p; the layout puts channel '
                    'order[p] of 3x3 position s in slot s*C + (p + s) % C (C % 4 == 0); for C % 4 == 1 the '
                    'conventional slot s*C + p (its bank is already (s + p) % 4)',
        order='position -> original channel; class of position p is p % 4 (fit.order_from_group)'), networks={})
    t0 = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(fit_network_2, label, MODELS[label], perms1[label]): label for label in labels}
        for fut in concurrent.futures.as_completed(futs):
            label = futs[fut]
            rec = fut.result()
            out['networks'][label] = rec
            print(f'L3 fit {label:<26}' + ' '.join(f'{r["layer"]}:{r["cal_saving_L3_vs_L2_pct"]:5.2f}%'
                                                   for r in rec['fitted']) + f'   ({rec["seconds"]} s)', flush=True)
    out['networks'] = {k: out['networks'][k] for k in labels}
    out['wall_seconds'] = round(time.time() - t0, 1)
    return out


# ----------------------------------------------------------------------------- 2. the count

def digest(perms1, perms2, label):
    blob = json.dumps([perms1[label]['orders'], perms2[label]['orders']], sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def net_state(label):
    """Per worker: the network's layers and, per fitted layer, the window columns of each layout."""
    if label in _STATE:
        return _STATE[label]
    model = MODELS[label]
    man, layers = run_denoise.load_layers(export_dir(model))
    assert man['sigma'] == SIGMA, (model, man['sigma'])
    o1 = json.loads((HERE/'perms.json').read_text())['networks'][label]['orders']
    o3 = json.loads(PERMS_2.read_text())['networks'][label]['orders']
    oms = multistart_orders(layers) if label == MS_LABEL else None
    lay = {}
    for L in fitted_layers(layers):
        taps, cin = taps_and_channels(L)
        p = L['inputs'][0]
        ident = np.arange(cin)
        rec = dict(taps=taps, cin=cin, cols={
            'L1': permuted_columns(o1[p], taps), 'L2': skew_columns(ident, taps), 'L3': skew_columns(o3[p], taps)},
            groups={'L1': group_from_order(o1[p]), 'L2': ident % T, 'L3': group_from_order(o3[p])})
        assert check_bank_rule(rec['cols']['L2'], rec['groups']['L2'], taps)
        assert check_bank_rule(rec['cols']['L3'], rec['groups']['L3'], taps)
        if oms is not None:
            rec['cols'][MS] = permuted_columns(oms[p], taps)
        lay[L['name']] = rec
    int_eval = json.loads((export_dir(model)/'int_eval.json').read_text())
    _STATE[label] = (man, layers, lay, int_eval)
    return _STATE[label]


def set_state(set_name):
    key = ('set', set_name)
    if key not in _STATE:
        _STATE[key] = {name: (clean, noisy) for name, clean, noisy in test_noise(load_set(set_name), SIGMA, seed=0)}
    return _STATE[key]


def count_image(label, set_name, image, tag, path):
    """Per layer the summed window cycles of every layout at W = 1, 2, 4 on one image -> cache file."""
    t0 = time.time()
    man, layers, lay, int_eval = net_state(label)
    clean, noisy = set_state(set_name)[image]
    names = LAYOUTS + ((MS,) if label == MS_LABEL else ())
    rows = []

    def hook(L, x, acc):
        k, cout = L['K'], L['COUT']
        base = {w: int(window_cycles(x, k, cout, w).sum()) for w in WIDTHS}
        row = dict(name=L['name'])
        if L['name'] not in lay:
            for w in WIDTHS:
                row[f'w{w}'] = [base[w]]*len(names)
            rows.append(row)
            return
        r = lay[L['name']]
        got = {}
        for n in names[1:]:
            xp = x[:, r['cols'][n]]
            got[n] = {w: window_cycles(xp, k, cout, w) for w in WIDTHS}
        # The W=4 count of L1, L2, L3 is the fits' fast objective on the same windows.
        n0 = residue_counts(x, r['taps'], r['cin'])
        ns = skew_residue_counts(x, r['taps'], r['cin'])
        for n, res in (('L1', n0), ('L2', ns), ('L3', ns)):
            if not np.array_equal(got[n][4], fast_cycles(res, r['groups'][n], k, cout, 4)):
                raise AssertionError(f'{label} {set_name} {image} {L["name"]} {n}: fast objective != window_cycles')
        for w in WIDTHS:
            row[f'w{w}'] = [base[w]] + [int(got[n][w].sum()) for n in names[1:]]
        rows.append(row)

    out = emulate(man, layers, np.rint(noisy*QMAX_A).astype(np.uint8), hook)
    p = float(psnr(clean, out.astype(np.float32)/255))
    rec = dict(network=label, set=set_name, image=image, digest=tag, layouts=list(names), psnr=p,
               psnr_matches_int_eval=abs(p - int_eval[set_name]['per_image'][image]) <= 1e-5, layers=rows,
               seconds=round(time.time() - t0, 2), started_at=t0, finished_at=time.time())
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(rec))
    tmp.replace(path)
    return label, set_name, image, rec['seconds']


# ----------------------------------------------------------------------------- 3. function preservation

def function_check(label, tag, path, fold_dir):
    """Set12 05.png, every layer, all windows: integer-oracle accumulators of L2 and of the folded L3."""
    t0 = time.time()
    model = MODELS[label]
    src = export_dir(model)
    man0, lay0 = run_denoise.load_layers(src)
    o3 = json.loads(PERMS_2.read_text())['networks'][label]['orders']
    fitted = {L['name'] for L in fitted_layers(lay0)}
    q_in, clean = noisy_input(*ALSO, man0['sigma'])
    ref = {}
    out0 = emulate(man0, lay0, q_in, lambda L, x, acc: ref.__setitem__(L['name'], (x.copy(), acc.copy())))
    rows = {L['name']: dict(layer=L['name'], skewed=L['name'] in fitted and (L['K']//(L['kh']*L['kw'])) % T == 0,
                            relabelled_input=L['name'] in fitted) for L in lay0}

    def skew_cols(L):
        taps, cin = L['kh']*L['kw'], L['K']//(L['kh']*L['kw'])
        return skew_columns(np.arange(cin), taps) if L['name'] in fitted else np.arange(L['K'])

    for L in lay0:
        x, acc = ref[L['name']]
        c = skew_cols(L)
        rows[L['name']]['emulation_is_oracle'] = bool(np.array_equal(oracle(x, L['wq'], L['bq']), acc))
        rows[L['name']]['L2_accumulators_equal'] = bool(np.array_equal(oracle(x[:, c], L['wq'][:, c], L['bq']), acc))
        rows[L['name']]['windows'] = int(x.shape[0])

    dest = fold_dir/model
    perm = fold(src, o3, dest)
    man1, lay1 = run_denoise.load_layers(dest)
    st = dict(L3=None)

    def check(L, x1, acc1):
        x0, a0 = ref[L['name']]
        src_idx, pout = perm[L['name']]
        taps = L['kh']*L['kw']
        c = skew_cols(L)
        r = rows[L['name']]
        r['L3_output_permuted'] = not np.array_equal(pout, np.arange(len(pout)))
        r['L3_folded_windows_are_relabelled_original'] = bool(np.array_equal(x1, x0[:, window_columns(src_idx, taps)]))
        r['L3_folded_accumulators_equal_up_to_column_order'] = bool(np.array_equal(acc1, a0[:, pout]))
        r['L3_skewed_accumulators_equal_up_to_column_order'] = bool(
            np.array_equal(oracle(x1[:, c], L['wq'][:, c], L['bq']), a0[:, pout]))
        if L['name'] in fitted:   # the windows counted for L3 are the folded network's, skewed
            taps_, cin = taps_and_channels(L)
            r['L3_counted_windows_are_folded_skewed'] = bool(np.array_equal(
                x1[:, c], x0[:, skew_columns(o3[L['inputs'][0]], taps_)]))

    out1 = emulate(man1, lay1, q_in, check)
    st['L3'] = bool(np.array_equal(out0, out1))
    rows = list(rows.values())
    keys2 = ('emulation_is_oracle', 'L2_accumulators_equal')
    keys3 = ('L3_folded_windows_are_relabelled_original', 'L3_folded_accumulators_equal_up_to_column_order',
             'L3_skewed_accumulators_equal_up_to_column_order')
    rec = dict(network=label, model=model, image=f'{ALSO[0]} {ALSO[1]}', digest=tag,
               oracle='scripts/run_cifar.oracle on every window of every layer',
               layers=rows, L2_all_layers_equal=all(r[k] for r in rows for k in keys2),
               L3_all_layers_equal_up_to_column_order=all(r[k] for r in rows for k in keys3) and all(
                   r.get('L3_counted_windows_are_folded_skewed', True) for r in rows),
               L3_folded_denoised_image_identical=st['L3'],
               layers_skewed=sum(r['skewed'] for r in rows), layers_relabelled_input=sum(
                   r['relabelled_input'] for r in rows), seconds=round(time.time() - t0, 1),
               started_at=t0, finished_at=time.time())
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(rec))
    tmp.replace(path)
    return label, rec['seconds']


# ----------------------------------------------------------------------------- 4. results

def saving(o, p):
    return 100*(np.asarray(o, np.float64) - p)/o


def load_cache(cache, labels, tags):
    per, checks = {}, {}
    for label in labels:
        d = cache/slug(label)
        per[label] = {}
        for s in SETS:
            for f in sorted(d.glob(f'{s}__*.json')):
                rec = json.loads(f.read_text())
                if rec['digest'] == tags[label]:
                    per[label][(s, rec['image'])] = rec
        f = d/'function_check.json'
        if f.exists():
            rec = json.loads(f.read_text())
            if rec['digest'] == tags[label]:
                checks[label] = rec
    return per, checks


def slug(label):
    return ''.join(ch if ch.isalnum() else '_' for ch in label)


def totals(rec, w, i):
    return sum(r[f'w{w}'][i] for r in rec['layers'])


def head_keys(per_image):
    return sorted(k for k in per_image if k != CALIB)


def layout_summary(per_image, keys, w, i, fitted):
    o = np.array([totals(per_image[k], w, 0) for k in keys], np.int64)
    p = np.array([totals(per_image[k], w, i) for k in keys], np.int64)
    s = saving(o, p)
    worse = sum(r[f'w{w}'][i] > r[f'w{w}'][0] for k in keys for r in per_image[k]['layers'] if r['name'] in fitted)
    return dict(images=len(keys), pooled_pct=float(saving(o.sum(), p.sum())), min_pct=float(s.min()),
                median_pct=float(np.median(s)), max_pct=float(s.max()), L0_cycles=int(o.sum()),
                layout_cycles=int(p.sum()), images_saving_le_0=int((s <= 0).sum()),
                image_layers=len(keys)*len(fitted), image_layers_worse=int(worse))


def ci(v):
    lo, hi = np.percentile(v, [2.5, 97.5])
    return [float(lo), float(hi)]


def network_results(label, per_image, fitted, idx, names):
    keys = head_keys(per_image)
    out = {}
    for w in WIDTHS:
        o = np.array([totals(per_image[k], w, 0) for k in keys], np.int64)
        ps = {n: np.array([totals(per_image[k], w, i) for k in keys], np.int64) for i, n in enumerate(names)}
        so = o[idx].sum(1)
        boot = {n: 100*(so - ps[n][idx].sum(1))/so for n in names[1:]}
        rec = {}
        for i, n in enumerate(names[1:], 1):
            rec[n] = layout_summary(per_image, keys, w, i, fitted)
            rec[n]['bootstrap_95_pct'] = ci(boot[n])
            for key, tag in ((ALSO, '05.png'), (CALIB, '01.png')):
                a, b = totals(per_image[key], w, 0), totals(per_image[key], w, i)
                rec[n][tag] = dict(L0=a, layout=b, saving_pct=float(saving(a, b)))
            rec[n]['per_layer_pooled_79_pct'] = {f: float(saving(*(sum(
                r[f'w{w}'][j] for k in keys for r in per_image[k]['layers'] if r['name'] == f) for j in (0, i))))
                for f in fitted}
        s2, s3 = saving(o, ps['L2']), saving(o, ps['L3'])
        d = s3 - s2
        rec['L3_minus_L2'] = dict(
            pooled_pct_points=rec['L3']['pooled_pct'] - rec['L2']['pooled_pct'],
            bootstrap_95_pct_points=ci(boot['L3'] - boot['L2']),
            per_image_min=float(d.min()), per_image_median=float(np.median(d)), per_image_max=float(d.max()),
            images_L3_below_L2=int((ps['L3'] < ps['L2']).sum()), images_L3_above_L2=int((ps['L3'] > ps['L2']).sum()))
        out[f'w{w}'] = rec
    return out


def cross_checks(labels, per, res1, skew, b32):
    """Asserted: L0/L1 == results.json, B-32 s1 L2 == skew_count.json (and the 05.png networks there),
    10 x 45 L2 == L0 and L3 == L1, B-32 s1 L0/L1/Multi-start == b32_testsets.json."""
    out = {}
    for label in labels:
        pi = per[label]
        r1 = res1['networks'][label]['per_image']
        assert set(r1) == {f'{s}/{n}' for s, n in pi}, label
        for (s, n), rec in pi.items():
            for w in WIDTHS:
                assert [totals(rec, w, 0), totals(rec, w, 1)] == r1[f'{s}/{n}'][f'w{w}'], (label, s, n, w)
        out[f'{label}: L0 and L1 totals == results.json original and permuted (80 images, W=1,2,4)'] = True
    for label, net in skew['networks'].items():
        if label not in per:
            continue
        for key, v in net['images'].items():
            s, n = key.split(' ')
            rec = per[label][(s, n)]
            for w in WIDTHS:
                assert totals(rec, w, 0) == v['conventional'][f'w{w}'], (label, key, w)
                assert totals(rec, w, 2) == v['skewed'][f'w{w}'], (label, key, w)
        out[f'{label}: L0 and L2 totals == skew_count.json conventional and skewed '
            f'({len(net["images"])} image(s), W=1,2,4)'] = True
    assert MS_LABEL not in per or len(skew['networks'][MS_LABEL]['images']) == 80
    lab45 = '10 x 45 ReLU + QAT'
    if lab45 in per:
        for rec in per[lab45].values():
            for r in rec['layers']:
                for w in WIDTHS:
                    v = r[f'w{w}']
                    assert v[2] == v[0] and v[3] == v[1], (rec['image'], r['name'], w)
        out[f'{lab45}: L2 == L0 and L3 == L1 on every layer of every image (W=1,2,4)'] = True
    if MS_LABEL in per:
        for e in b32['images']:
            rec = per[MS_LABEL][(e['set'], e['image'])]
            ms = rec['layouts'].index(MS)
            for w in WIDTHS:
                got = [totals(rec, w, 0), totals(rec, w, 1), totals(rec, w, ms)]
                assert got == [e[f'w{w}'][k] for k in ('original', 'frozen', 'multistart')], (e['image'], w)
        out[f'{MS_LABEL}: L0, L1 and Multi-start totals == b32_testsets.json original, frozen, multistart '
            f'(80 images, W=1,2,4)'] = True
    return out


def assemble(labels, per, checks, perms1, perms2, cache, args):
    bounds = json.loads((HERE/'bounds.json').read_text())['networks']
    res1 = json.loads((HERE/'results.json').read_text())
    skew = json.loads((HERE/'skew_count.json').read_text())
    b32 = json.loads(B32_TESTSETS.read_text())
    keys = head_keys(per[labels[0]])
    assert len(keys) == 79
    idx = np.random.default_rng(BOOT_SEED).integers(0, len(keys), size=(N_BOOT, len(keys)))
    nets = {}
    for label in labels:
        pi = per[label]
        assert len(pi) == 80 and head_keys(pi) == keys, (label, len(pi))
        names = tuple(pi[keys[0]]['layouts'])
        fitted = [r['layer'] for r in perms1[label]['fitted']]
        cin = sorted({r['C_in'] for r in perms1[label]['fitted']})
        fc = checks[label]
        rec = dict(model=MODELS[label], fitted_layers=fitted, C_in_of_fitted_layers=cin,
                   C_mod_4_is_0=all(c % T == 0 for c in cin), can_pay=bounds[label]['can_pay'],
                   layouts=list(names),
                   psnr_checks=f'{sum(v["psnr_matches_int_eval"] for v in pi.values())}/80 match int_eval.json',
                   count_cpu_seconds=round(sum(v['seconds'] for v in pi.values())),
                   function_preservation_05png=dict(
                       L2_all_layers_equal=fc['L2_all_layers_equal'],
                       L3_all_layers_equal_up_to_column_order=fc['L3_all_layers_equal_up_to_column_order'],
                       L3_folded_denoised_image_identical=fc['L3_folded_denoised_image_identical'],
                       layers=len(fc['layers']), layers_skewed=fc['layers_skewed'],
                       layers_relabelled_input=fc['layers_relabelled_input'], windows_per_layer=sorted(
                           {r['windows'] for r in fc['layers']}), seconds=fc['seconds'], per_layer=fc['layers']),
                   summary_79=network_results(label, pi, fitted, idx, names))
        assert all(v['psnr_matches_int_eval'] for v in pi.values()), label
        assert fc['L2_all_layers_equal'] and fc['L3_all_layers_equal_up_to_column_order'], label
        assert fc['L3_folded_denoised_image_identical'], label
        rec['per_image_totals'] = {f'{s}/{n}': {f'w{w}': [totals(v, w, i) for i in range(len(names))]
                                               for w in WIDTHS} for (s, n), v in sorted(pi.items())}
        worse = {}
        for (s, n), v in sorted(pi.items()):
            for w in WIDTHS:
                for i, lay in enumerate(names[1:], 1):
                    lw = [r['name'] for r in v['layers'] if r[f'w{w}'][i] > r[f'w{w}'][0]]
                    if lw:
                        worse.setdefault(f'{s}/{n}', {})[f'{lay}_w{w}'] = lw
        rec['image_layers_worse_than_L0'] = worse
        nets[label] = rec

    xc = cross_checks(labels, per, res1, skew, b32)

    # H4: zero wherever bounds.json says zero, on all 80 images (totals; also every layer).
    h4 = {}
    for label in labels:
        pi = per[label]
        for w in WIDTHS:
            if bounds[label]['can_pay'][f'w{w}']:
                continue
            tot = {n: all(totals(v, w, i) == totals(v, w, 0) for v in pi.values()) for i, n in ((2, 'L2'), (3, 'L3'))}
            lay = all(r[f'w{w}'][i] == r[f'w{w}'][0] for v in pi.values() for r in v['layers'] for i in (2, 3))
            h4.setdefault(label, {})[f'w{w}'] = dict(L2_equals_L0_all_80=tot['L2'], L3_equals_L0_all_80=tot['L3'],
                                                     every_layer_too=lay)
    pooled = lambda label, n, w=4: nets[label]['summary_79'][f'w{w}'][n]['pooled_pct']  # noqa: E731
    nine = [label for label in labels if nets[label]['C_mod_4_is_0']]
    h5 = {label: dict(L1_pooled_pct=pooled(label, 'L1'), L2_pooled_pct=pooled(label, 'L2'),
                      L2_minus_L1_pct_points=pooled(label, 'L2') - pooled(label, 'L1'),
                      L1_bootstrap_95=nets[label]['summary_79']['w4']['L1']['bootstrap_95_pct'],
                      L2_bootstrap_95=nets[label]['summary_79']['w4']['L2']['bootstrap_95_pct'],
                      L2_gt_L1=pooled(label, 'L2') > pooled(label, 'L1')) for label in nine}
    h6 = {label: dict(L2_pooled_pct=pooled(label, 'L2'), L3_pooled_pct=pooled(label, 'L3'),
                      L3_minus_L2_pct_points=nets[label]['summary_79']['w4']['L3_minus_L2']['pooled_pct_points'],
                      L3_minus_L2_bootstrap_95=nets[label]['summary_79']['w4']['L3_minus_L2']['bootstrap_95_pct_points'],
                      L3_gt_L2=pooled(label, 'L3') > pooled(label, 'L2')) for label in nine}
    verdicts = dict(
        H4=dict(claim='wherever bounds.json says zero, L2 and L3 count exactly as L0 on every image (80)',
                checked=h4, holds=all(v[k] for d in h4.values() for v in d.values()
                                      for k in ('L2_equals_L0_all_80', 'L3_equals_L0_all_80'))),
        H5=dict(claim='at W=4 the pooled saving (79 images) of L2 > that of L1 on every network with C % 4 == 0',
                networks=nine, per_network=h5, holds=all(v['L2_gt_L1'] for v in h5.values())))
    if len(nine) != 9:
        verdicts['H5']['note'] = f'{len(nine)} networks with C % 4 == 0, not nine'
    b = h6.get(MS_LABEL, {}).get('L3_minus_L2_bootstrap_95')
    excl = b is not None and (b[0] > 0 or b[1] < 0)
    verdicts['H6'] = dict(claim='at W=4 the pooled saving of L3 > that of L2 on every network with C % 4 == 0, and on '
                                'B-32 ReLU s1 the 95% bootstrap interval of L3 - L2 excludes 0',
                          networks=nine, per_network=h6, all_L3_gt_L2=all(v['L3_gt_L2'] for v in h6.values()),
                          b32_relu_s1_interval=b, b32_relu_s1_interval_excludes_0=excl,
                          holds=all(v['L3_gt_L2'] for v in h6.values()) and excl)
    if MS_LABEL in nets:
        verdicts['H5']['context_multistart_b32_relu_s1'] = dict(
            multistart_pooled_pct=pooled(MS_LABEL, MS), L2_pooled_pct=pooled(MS_LABEL, 'L2'),
            L2_gt_multistart=pooled(MS_LABEL, 'L2') > pooled(MS_LABEL, MS),
            note='context only: H5 uses perms.json (= the published Frozen groups on this network, H0)')

    runs = json.loads((cache/'runs.json').read_text()) if (cache/'runs.json').exists() else []
    starts = [v['started_at'] for p in per.values() for v in p.values()] + [c['started_at'] for c in checks.values()]
    ends = [v['finished_at'] for p in per.values() for v in p.values()] + [c['finished_at'] for c in checks.values()]
    res = dict(
        protocol='bankperm/PROTOCOL_2.md (committed 951c8f1)', deviations='bankperm/DEVIATIONS_2.md',
        layouts=dict(L0='conventional, bank (s*C + p) % 4', L1='perms.json orders (PROTOCOL.md recipe)',
                     L2='skew: slot s*C + (p + s) % C, bank (s + p) % 4 (C % 4 == 0); = L0 for C % 4 == 1',
                     L3='perms_2.json orders (fit under the skewed rule), then skewed; = L1 for C % 4 == 1',
                     L1_multistart='B-32 ReLU s1 only, context: the published Multi-start groups'),
        layout_order_in_lists='per_image_totals[image][wN] = [L0, L1, L2, L3] (+ L1_multistart on B-32 ReLU s1)',
        images='Set12 (12) + BSD68 (68), sigma 25, test_noise seed 0, host emulation of the original network',
        count='sum over conv1-convL of predict_w4.window_cycles (sparse mode) on the layout\'s windows; '
              'fill and drain left out',
        headline='the 79 images other than Set12 01.png (the calibration image of L1 and L3)',
        saving='100 * (L0 - layout) / L0; pooled = on the summed counts',
        bootstrap=dict(resamples=N_BOOT, generator=f'np.random.default_rng({BOOT_SEED}).integers(0, 79, (10000, 79)), '
                       'drawn once and used for every network, width and layout (paired; L3 - L2 resamples the '
                       'images jointly)', interval='95% percentile, np.percentile 2.5 / 97.5 (linear)',
                       statistic='pooled saving of the resampled images'),
        cross_checks=xc, verdicts=verdicts, networks=nets,
        runtimes=dict(fit_L3_seconds={k: v['seconds'] for k, v in perms2.items()},
                      count_cpu_seconds={k: v['count_cpu_seconds'] for k, v in nets.items()},
                      function_check_seconds={k: checks[k]['seconds'] for k in labels},
                      first_task_start_to_last_task_end_seconds=round(max(ends) - min(starts)),
                      runs=runs))
    write_json(args.out, res)
    return res


def print_table(res):
    print(f'\n{"network":<26}{"W":>2} ' + ' '.join(f'{n:>22}' for n in ('L1', 'L2', 'L3', 'L3-L2')))
    for label, net in res['networks'].items():
        for w in (2, 4):
            s = net['summary_79'][f'w{w}']
            cells = [f'{s[n]["pooled_pct"]:6.2f} [{s[n]["bootstrap_95_pct"][0]:6.2f},{s[n]["bootstrap_95_pct"][1]:6.2f}]'
                     for n in ('L1', 'L2', 'L3')]
            d = s['L3_minus_L2']
            cells.append(f'{d["pooled_pct_points"]:6.2f} [{d["bootstrap_95_pct_points"][0]:6.2f},'
                         f'{d["bootstrap_95_pct_points"][1]:6.2f}]')
            print(f'{label:<26}{w:>2} ' + ' '.join(f'{c:>22}' for c in cells))
    for k, v in res['verdicts'].items():
        print(k, 'holds' if v['holds'] else 'FAILS', '-', v['claim'])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--networks', help='comma-separated labels (default: all ten)')
    ap.add_argument('--cache', type=Path, default=Path(tempfile.gettempdir())/'bankperm_evaluate_2',
                    help='per-image and per-network results; a rerun skips what is here')
    ap.add_argument('--no-assemble', action='store_true', help='count and check only')
    ap.add_argument('--out', type=Path, default=HERE/'results_2.json')
    args = ap.parse_args()
    t_run = time.time()
    labels = args.networks.split(',') if args.networks else list(MODELS)
    assert all(label in MODELS for label in labels), labels
    args.cache.mkdir(parents=True, exist_ok=True)

    # 1. L3 fit (all ten networks, once).
    if not PERMS_2.exists():
        write_json(PERMS_2, fit_all(list(MODELS), args.jobs))
        print('wrote', PERMS_2, flush=True)
    perms1 = json.loads((HERE/'perms.json').read_text())['networks']
    perms2 = json.loads(PERMS_2.read_text())['networks']
    tags = {label: digest(perms1, perms2, label) for label in MODELS}

    # 2-3. Count and function check what is not cached.
    per, checks = load_cache(args.cache, labels, tags)
    order = sorted(labels, key=lambda k: -json.loads((HERE/'results.json').read_text())['networks'][k]['cpu_seconds'])
    todo = []
    for label in order:
        (args.cache/slug(label)).mkdir(exist_ok=True)
        if label not in checks:
            todo.append(('check', label))
        for s in reversed(SETS):
            for name, _ in load_set(s):
                if (s, name) not in per[label]:
                    todo.append(('count', label, s, name))
    print(f'{len(todo)} task(s) to run ({sum(t[0] == "count" for t in todo)} image counts, '
          f'{sum(t[0] == "check" for t in todo)} function checks)', flush=True)
    done = 0
    if todo:
        fold_dir = args.cache/'folded_L3'
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futs = []
            for t in todo:
                d = args.cache/slug(t[1])
                if t[0] == 'check':
                    futs.append(pool.submit(function_check, t[1], tags[t[1]], d/'function_check.json', fold_dir))
                else:
                    futs.append(pool.submit(count_image, t[1], t[2], t[3], tags[t[1]], d/f'{t[2]}__{t[3]}.json'))
            for fut in concurrent.futures.as_completed(futs):
                r = fut.result()
                done += 1
                print(f'[{done}/{len(todo)}] ' + ' '.join(map(str, r)) + f'  ({time.time() - t_run:.0f} s)', flush=True)
    runs_f = args.cache/'runs.json'
    runs = json.loads(runs_f.read_text()) if runs_f.exists() else []
    runs.append(dict(networks=labels, tasks=len(todo), wall_seconds=round(time.time() - t_run), jobs=args.jobs,
                     ended=time.strftime('%Y-%m-%d %H:%M:%S')))
    runs_f.write_text(json.dumps(runs, indent=1) + '\n')

    # 4. Results (only with every network: the verdicts are over all of them).
    if args.no_assemble or args.networks:
        print('counted; no results written (run without --networks/--no-assemble to assemble)')
        return
    per, checks = load_cache(args.cache, labels, tags)
    missing = [label for label in labels if len(per[label]) != 80 or label not in checks]
    if missing:
        raise SystemExit(f'not all cached yet: {missing}; rerun to finish')
    res = assemble(labels, per, checks, perms1, perms2, args.cache, args)
    print_table(res)
    print('wrote', args.out)


if __name__ == '__main__':
    main()
