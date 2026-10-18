"""Fit the channel-to-bank permutation of every network, by the recipe of PROTOCOL.md.

    python bankperm/fit.py            # writes bankperm/perms.json (about 2 minutes)

One fixed recipe, the Frozen recipe of scripts/q1_reviewer_bank.py, run on the
ten networks of denoise/count_test_sets.py MODELS:

  * calibration: Set12 01.png, the network's sigma, test_noise seed 0, the
    board driver's host emulation (scripts/run_denoise.py); every layer's
    windows are captured as the driver builds them (as predict_w4.layer_windows
    does for 05.png);
  * fitted layers: conv2 .. conv(L-1), whose input channels are the outputs of
    conv1 .. conv(L-2); per fitted layer 2048 windows drawn without replacement
    by ONE np.random.default_rng(42), consumed in layer order;
  * objective: mean W=4 window cycles on those windows,
    max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT) (predict_w4);
  * search: q1_reviewer_bank.fit_group as written -- identity start, 400
    proposals that swap two channels of different position classes, kept only
    if the objective falls by more than 1e-10, generator seed 42 + the index of
    the layer among the fitted layers.

The consumer's im2col order is (ky, kx, channel) (run_cifar.im2col, checked
below on a coded map), so tap t = s*C_in + p sits in bank t % 4 = ((s*C_in) % 4
+ p) % 4. A permutation therefore only decides each channel's position class
p % 4 (class sizes those of the identity layout; 12/11/11/11 for C_in = 45).
The objective is computed from per-window, per-channel nonzero counts split by
the residue (s*C_in) % 4 of the 3x3 position, and is checked on the calibration
windows against predict_w4.window_cycles applied to the column-permuted windows.
For C_in % 4 == 0 the search is q1_reviewer_bank.fit_group itself; the general
search used for C_in = 45 is checked to give the same groups on those layers.

H0: on B-32 ReLU s1 the result is compared with the published Frozen groups
(research/q1_codesign/bank_export_perm.json and the Frozen ZIP's
permutation_manifest.json). If they differ, the published groups are the ones
used for that network (PROTOCOL.md) and perms.json says so.

perms.json, per network: per fitted layer the new channel order (position ->
original channel), the class of each original channel, and the calibration mean
before and after; `orders` (keyed by the producer, as bank_export_perm.json) is
what evaluate.py and fold.py use.
"""
import contextlib
import io
import json
import math
import re
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from count_test_sets import MODELS  # noqa: E402
from predict_w4 import P, T, window_cycles  # noqa: E402
from q1_reviewer_bank import encode_order, fit_group  # noqa: E402
from run_cifar import im2col  # noqa: E402

CALIB = ('Set12', '01.png')
SEED, STEPS, SAMPLE, FIT_W = 42, 400, 2048, 4
H0_LABEL = 'B-32 ReLU + QAT s1'
PUBLISHED = ROOT/'research'/'q1_codesign'/'bank_export_perm.json'
FROZEN_ZIP = ROOT/'research'/'q1_codesign'/'artifacts'/'q1_bank_reordered_export_20261018.zip'


def write_json(path, obj):
    """indent=1 JSON with every list of plain numbers on one line."""
    text = json.dumps(obj, indent=1)
    flat = lambda m: '[' + ', '.join(v.strip() for v in m.group(0)[1:-1].split(',')) + ']'
    path.write_text(re.sub(r'\[[^\[\]{}"]+\]', flat, text) + '\n')


def export_dir(model):
    return ROOT/'denoise'/'export'/model


def noisy_input(set_name, image, sigma):
    """(7-bit noisy input, clean image) of one test image, test_noise seed 0."""
    name, clean, noisy = next(t for t in test_noise(load_set(set_name), sigma, seed=0) if t[0] == image)
    return np.rint(noisy*QMAX_A).astype(np.uint8), clean


def emulate(man, layers, q_in, hook):
    """run_denoise.denoise in host emulation; hook(L, x, acc) sees every layer's windows
    and INT32 accumulators. -> the denoised 8-bit image."""
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        acc, info = real(L, x, args, tag)
        hook(L, x, acc)
        return acc, info

    run_denoise.run_layer = capture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'bankperm')
    finally:
        run_denoise.run_layer = real
    return out


def fitted_layers(layers):
    """The consumers whose input channels are permuted: conv2 .. conv(L-1)."""
    out = layers[1:-1]
    for L in out:
        if len(L['inputs']) != 1 or L['inputs'][0] == 'image':
            raise SystemExit(f'{L["name"]}: a permuted consumer must read one hidden map, reads {L["inputs"]}')
    return out


def taps_and_channels(L):
    taps = L['kh']*L['kw']
    cin, r = divmod(L['K'], taps)
    assert r == 0, (L['name'], L['K'])
    return taps, cin


def check_im2col_order(c=5, h=6, w=7):
    """run_cifar.im2col puts channel ch of 3x3 position s = ky*3+kx at column s*C + ch."""
    q = (np.arange(c)[:, None, None]*1000 + np.arange(h)[None, :, None]*10 + np.arange(w)[None, None, :] + 1)
    x = im2col(q[None].astype(np.int64))
    for oy in range(h):
        for ox in range(w):
            row = x[oy*w + ox]
            for ky in range(3):
                for kx in range(3):
                    iy, ix = oy + ky - 1, ox + kx - 1
                    for ch in range(c):
                        want = q[ch, iy, ix] if 0 <= iy < h and 0 <= ix < w else 0
                        assert row[(ky*3 + kx)*c + ch] == want
    return True


def residue_counts(x, taps, cin):
    """(N, K) windows -> (N, C_in, 4) uint8: per window and channel, the nonzero taps
    at 3x3 positions s with (s*C_in) % 4 == a, a = 0..3."""
    nz = (x != 0).reshape(len(x), taps, cin)
    res = (np.arange(taps)*cin) % T
    n = np.zeros((len(x), cin, T), np.uint8)
    for a in range(T):
        if (res == a).any():
            n[:, :, a] = nz[:, res == a, :].sum(1)
    return n


def bank_counts(n, group):
    """Nonzero taps per bank, (N, 4), when original channel c sits in position class group[c]:
    its taps at residue a land in bank (a + group[c]) % 4."""
    cin = n.shape[1]
    idx = (np.arange(T)[None, :] - np.asarray(group)[:, None]) % T          # (C, bank) -> residue
    return n[:, np.arange(cin)[:, None], idx].sum(1, dtype=np.int32)


def fast_cycles(n, group, k, cout, w):
    """Per-window cycles from the residue counts; equals predict_w4.window_cycles on the
    column-permuted windows (checked in fit_network)."""
    issue = math.ceil(cout/P)*np.maximum(bank_counts(n, group).max(1), 1)
    return np.maximum(np.maximum(math.ceil(k/w) + 1, issue), cout)


def fit_general(n, k, cout, seed, steps):
    """fit_group's search for any C_in: same start, proposals, generator use and acceptance."""
    nch = n.shape[1]
    rng = np.random.default_rng(seed)
    group = np.arange(nch, dtype=np.int32) % T
    best = float(np.mean(fast_cycles(n, group, k, cout, FIT_W)))
    accepted = 0
    for _ in range(steps):
        p = int(rng.integers(0, nch))
        choices = np.flatnonzero(group != group[p])
        q = int(choices[int(rng.integers(0, len(choices)))])
        group[p], group[q] = group[q], group[p]
        trial = float(np.mean(fast_cycles(n, group, k, cout, FIT_W)))
        if trial + 1e-10 < best:
            best = trial
            accepted += 1
        else:
            group[p], group[q] = group[q], group[p]
    return group, best, accepted


def order_from_group(group):
    """position -> original channel: the channels of class r, in increasing index, fill the
    positions p with p % 4 == r in increasing order (encode_order for equal classes)."""
    group = np.asarray(group)
    order = np.empty(len(group), np.int64)
    for r in range(T):
        pos = np.arange(r, len(group), T)
        ch = np.flatnonzero(group == r)
        if len(ch) != len(pos):
            raise AssertionError(f'class {r} holds {len(ch)} channels for {len(pos)} positions')
        order[pos] = ch
    return order


def group_from_order(order):
    group = np.empty(len(order), np.int64)
    group[np.asarray(order)] = np.arange(len(order)) % T
    return group


def permuted_columns(order, taps):
    """Column s*C + p of the permuted layout's window is column s*C + order[p] of the original."""
    order = np.asarray(order)
    return (np.arange(taps)[:, None]*len(order) + order[None, :]).reshape(-1)


def fit_network(label, model):
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
    rows, orders = [], {}
    for i, L in enumerate(fit):
        k, cout = L['K'], L['COUT']
        taps, cin = taps_and_channels(L)
        x = wins[L['name']]
        sel = rng.choice(len(x), size=min(SAMPLE, len(x)), replace=False)
        xs = x[sel]
        n = residue_counts(xs, taps, cin)
        group, best, accepted = fit_general(n, k, cout, SEED + i, STEPS)
        identity = np.arange(cin) % T
        before = float(np.mean(fast_cycles(n, identity, k, cout, FIT_W)))
        if cin % T == 0:
            # The recipe as written: q1_reviewer_bank.fit_group on per-channel counts.
            assert not n[:, :, 1:].any()
            g_ref, best_ref = fit_group(n[:, :, 0], cout, k, SEED + i, STEPS)
            if not (np.array_equal(g_ref, group) and best_ref == best):
                raise AssertionError(f'{label} {L["name"]}: general search differs from fit_group')
            order = encode_order(g_ref)
            assert np.array_equal(order, order_from_group(group))
        else:
            order = order_from_group(group)
        assert np.array_equal(group_from_order(order), group)
        # The objective is predict_w4.window_cycles on the column-permuted windows.
        control = np.random.default_rng(1000 + i).permutation(cin)
        for o in (np.arange(cin), order, control):
            cols = permuted_columns(o, taps)
            for w in (1, 2, 4):
                if not np.array_equal(window_cycles(xs[:, cols], k, cout, w),
                                      fast_cycles(n, group_from_order(o), k, cout, w)):
                    raise AssertionError(f'{label} {L["name"]} W={w}: fast objective differs from window_cycles')
        producer = L['inputs'][0]
        orders[producer] = order.tolist()
        rows.append(dict(layer=L['name'], producer=producer, C_in=cin, K=k, COUT=cout, seed=SEED + i,
                         calibration_windows=int(len(sel)), of_windows=int(len(x)),
                         class_sizes=[int((group == r).sum()) for r in range(T)],
                         cal_mean_before=before, cal_mean_after=best,
                         cal_saving_pct=100*(before - best)/before, accepted_swaps=accepted,
                         order=order.tolist(), class_of_original_channel=group.tolist()))
    return dict(model=model, sigma=man['sigma'], fitted=rows, orders=orders,
                orders_source='this fit', seconds=round(time.time() - t0, 1))


def h0(rec):
    """Compare the fit on B-32 ReLU s1 with the published Frozen groups."""
    pub = json.loads(PUBLISHED.read_text())
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        zman = json.loads(z.read(f'{rec["model"]}/permutation_manifest.json'))
    assert pub['model'] == rec['model']
    layers = []
    for row in rec['fitted']:
        p = row['producer']
        mine, theirs = row['order'], pub['orders'].get(p)
        g_mine, g_theirs = np.array(row['class_of_original_channel']), group_from_order(theirs)
        layers.append(dict(layer=row['layer'], producer=p, order_identical=mine == theirs,
                           channels_in_another_class=int((g_mine != g_theirs).sum())))
    same = all(r['order_identical'] for r in layers) and set(pub['orders']) == set(rec['orders'])
    out = dict(published=str(PUBLISHED.relative_to(ROOT)),
               published_equals_zip_permutation_manifest=pub['orders'] == zman['orders'],
               exact_match=bool(same), layers=layers)
    if not same:
        rec['orders_fitted_here'] = rec['orders']
        rec['orders'] = pub['orders']
        rec['orders_source'] = 'published Frozen groups (H0 failed; PROTOCOL.md)'
    return out


def main():
    assert check_im2col_order()
    out = dict(protocol='bankperm/PROTOCOL.md', recipe=dict(
        calibration=f'{CALIB[0]} {CALIB[1]}, sigma of the network, test_noise seed 0, host emulation',
        windows_per_layer=SAMPLE, window_generator=f'one np.random.default_rng({SEED}) per network, layer order',
        objective='mean W=4 window cycles, max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT)',
        search=f'q1_reviewer_bank.fit_group: identity start, {STEPS} swaps of channels in different classes, '
               f'accept if the objective falls by > 1e-10, seed {SEED} + fitted-layer index',
        bank_of_tap='(s*C_in + p) % 4, im2col order (ky, kx, channel), checked on a coded map',
        order='position -> original channel; class of position p is p % 4'), networks={})
    for label, model in MODELS.items():
        rec = fit_network(label, model)
        if label == H0_LABEL:
            out['H0'] = h0(rec)
        out['networks'][label] = rec
        print(f'{label:<26}' + ' '.join(f'{r["layer"]}:{r["cal_saving_pct"]:5.2f}%' for r in rec['fitted'])
              + f'   ({rec["seconds"]} s)', flush=True)
    h = out['H0']
    print('H0 (fit == published Frozen groups):', h['exact_match'],
          '' if h['exact_match'] else [(r['layer'], r['channels_in_another_class']) for r in h['layers']])
    write_json(HERE/'perms.json', out)
    print('wrote', HERE/'perms.json')


if __name__ == '__main__':
    main()
