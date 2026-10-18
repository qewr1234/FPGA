"""Baselines for the channel-to-bank permutation of B-32 ReLU + QAT s1 (W=4 count, sigma 25).

    python bankperm/baselines.py [--jobs 2]     # writes bankperm/baselines.json (about 10 minutes on 2 cores)

Network dn_d10_c32_us_fx_qat (count_test_sets.MODELS 'B-32 ReLU + QAT s1'),
whose Frozen and Multi-start layouts GPT exported and ran on the W=4 board.
Every layout is an assignment of the 32 input channels of conv2 .. conv9 to the
four position classes p % 4 (8 channels each; bank of tap s*32 + p is p % 4,
PROTOCOL.md). Its W=4 count on an image is the per-window
predict_w4.window_cycles of the original windows with the columns permuted,
summed over conv1-conv10 (fill and drain left out); conv1 and conv10 are the
same in every layout.

Calibration data (both reproduced from the original export's host emulation):
  C1  the recipe of PROTOCOL.md: Set12 01.png, test_noise seed 0, 2048 windows
      per fitted layer drawn by one np.random.default_rng(42) in layer order
      (fit.py; fit_group on these reproduces the published Frozen groups).
  C3  Multi-start's data (q1_gpu_deadline_suite.load_or_fit): Set12 01/02/03,
      noise seeds 0 and 1, per image, seed and layer 1024 windows drawn by
      np.random.default_rng(seed*1000 + layer number); 6144 windows per layer.

Layouts:
  (a) identity.
  (b) density sort, calibration C1 and C3: channels ranked by their mean nonzero
      taps per calibration window (q1_reviewer_bank.py's density control), dealt
      round-robin (0,1,2,3,0,1,...) or snake (0,1,2,3,3,2,1,0,...).
  (c) mean-NNZ balance (LPT): channels in decreasing mean, each into the class
      with the smallest summed mean that still has room.
  (d) Sense-like dynamic sort (Sun et al., IEEE TVLSI 2023): per image and layer,
      channels ranked by the nonzero count of that image's input feature map,
      dealt round-robin; snake and LPT variants. It needs the image's maps before
      the layer runs, i.e. ranking hardware, which this core does not have: NOT
      deployable here. Also, as the matched window-level oracle, the Frozen
      recipe fitted on the test image itself (2048 of its windows per layer,
      rng 42, 400 swaps): NOT deployable either.
  (e) 20 balanced random layouts (q1_reviewer_bank.py's control generator,
      default_rng(42 + 1000 + fitted-layer index)): median, the one with the
      lowest calibration objective (deployable), and the best per test image
      (NOT deployable, an oracle).
  (f) the published Frozen (bank_export_perm.json) and Multi-start
      (multistart_export_20261018.json) groups.
  (g) equal search budget. Multi-start (q1_gpu_deadline_suite, default settings)
      runs a greedy from the identity and 4 greedies from balanced random starts,
      400 proposals each, keeping the best: 5 * (1 + 400) = 2005 objective
      evaluations per layer, counting each start's first evaluation as
      q1_fair_budget.py does. Re-run here with optimizer seeds 42, 101, 202, 303,
      404 (seed 42 reproduces the published groups). Against it: the Frozen
      recipe (q1_reviewer_bank.fit_group, seed + fitted-layer index) with 2004
      proposals (2005 evaluations) on C3, the same 5 seeds. For context, also
      fit_group with 400 proposals on C3 and with 400 and 2004 on C1 (seed 42 at
      400 on C1 is the published Frozen).
  (h) bounds: per-window perfect balance, max bank = ceil(nnz/4) (no channel
      layout, static or per window, can count less), and the load/COUT floor
      max(ceil(K/4)+1, COUT).

Evaluation: the 79 test images other than Set12 01.png (C1's image) and the 77
other than Set12 01-03 (C3's images); sigma 25, test_noise seed 0. A method
calibrated on C3 is not clean on the 79 (02 and 03 are its calibration images,
at the same noise seed); the JSON flags that. Per method and set: pooled saving
(summed counts), per-image range and median, and the share of the
perfect-balance headroom captured, 100 * (original - layout) / (original -
perfect balance), pooled.

Checks: the original counts equal denoise/test_set_counts.json; on every image
and fitted layer the fast count of the identity, both published layouts, one
random layout and the Sense-like layout equals predict_w4.window_cycles on the column-permuted
windows; every layout counts at least the perfect-balance bound on every
image-layer; the published Frozen and Multi-start groups are reproduced by their
recipes and equal the ZIPs' permutation_manifest.json; on Set12 01.png the
self-fitted window oracle equals the Frozen groups; every denoised PSNR equals
int_eval.json; if bankperm/b32_testsets.json is present, the published layouts'
per-image counts equal its counts of the exported networks.
"""
import argparse
import concurrent.futures
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from count_test_sets import MODELS, SETS  # noqa: E402
from predict_w4 import P, T, window_cycles  # noqa: E402
from q1_gpu_deadline_suite import balanced_random, optimize  # noqa: E402
from q1_reviewer_bank import cycles, fit_group  # noqa: E402
from b32_board import ZIPS  # noqa: E402
from fit import (CALIB, PUBLISHED, SAMPLE, SEED, STEPS, check_im2col_order, emulate, export_dir,  # noqa: E402
                 fitted_layers, group_from_order, order_from_group, permuted_columns, residue_counts,
                 taps_and_channels, write_json)

LABEL = 'B-32 ReLU + QAT s1'
MODEL = MODELS[LABEL]
SIGMA, W = 25, 4
MULTI_JSON = ROOT/'research'/'q1_codesign'/'multistart_export_20261018.json'
C3_IMAGES, C3_NOISE_SEEDS, C3_WINDOWS = ('01.png', '02.png', '03.png'), (0, 1), 1024
MS_STARTS, MS_STEPS = 5, 400
BUDGET = MS_STARTS*(MS_STEPS + 1)                 # 2005 objective evaluations per layer
OPT_SEEDS = (42, 101, 202, 303, 404)              # q1_fair_budget.py's optimizer seeds
N_RANDOM = 20
CENTER = 4                                        # 3x3 position s = ky*3 + kx of the centre tap
FAMILIES = {   # name: (calibration, search, proposals per layer)
    'frozen_recipe_c1': ('C1', 'fit_group', STEPS),
    'greedy_budget_c1': ('C1', 'fit_group', BUDGET - 1),
    'frozen_recipe_c3': ('C3', 'fit_group', STEPS),
    'greedy_budget_c3': ('C3', 'fit_group', BUDGET - 1),
    'multistart_c3': ('C3', 'multistart', MS_STARTS*MS_STEPS),
}
DYNAMIC = ('sense_rr', 'sense_snake', 'sense_lpt', 'window_greedy_self')
EVAL_SETS = {
    '79': lambda s, n: not (s == 'Set12' and n == CALIB[1]),
    '77': lambda s, n: not (s == 'Set12' and n in C3_IMAGES),
}
_STATE = {}


# ----------------------------------------------------------------------------- layouts

def round_robin(n):
    return np.arange(n) % T


def snake(n):
    r = np.arange(n)
    return np.where((r//T) % 2 == 0, r % T, T - 1 - r % T)


def deal(weight, pattern):
    """Channels ranked by decreasing weight (stable), the r-th gets class pattern[r]."""
    g = np.empty(len(weight), np.int64)
    g[np.argsort(-np.asarray(weight, np.float64), kind='stable')] = pattern
    return g


def lpt(weight):
    """Largest first into the class with the smallest summed weight that has room (n/4 per class)."""
    weight = np.asarray(weight, np.float64)
    n = len(weight)
    load, room = np.zeros(T), np.full(T, n//T)
    g = np.empty(n, np.int64)
    for c in np.argsort(-weight, kind='stable'):
        ok = np.flatnonzero(room > 0)
        b = ok[np.argmin(load[ok])]
        g[c], load[b], room[b] = b, load[b] + weight[c], room[b] - 1
    return g


def density_layouts(table):
    mean = table.mean(0)
    n = len(mean)
    return dict(density_rr=deal(mean, round_robin(n)), density_snake=deal(mean, snake(n)), meannnz_lpt=lpt(mean))


def random_layouts(fit):
    """q1_reviewer_bank.py's 20 balanced random controls: per fitted layer i, default_rng(42+1000+i)."""
    out = [{} for _ in range(N_RANDOM)]
    for i, L in enumerate(fit):
        rng = np.random.default_rng(SEED + 1000 + i)
        for r in range(N_RANDOM):
            g = np.empty(32, np.int64)
            g[rng.permutation(32)] = np.arange(32) % T
            out[r][L['name']] = g
    return out


def multistart(table, cout, k, j, base):
    """q1_gpu_deadline_suite's multistart_greedy for layer index j (conv2 -> 1) with --seed base."""
    n = table.shape[1]
    best, v_best = optimize(table, cout, k, base + 100 + j, MS_STEPS)
    for rep in range(MS_STARTS - 1):
        start = balanced_random(n, base + 300 + 100*j + rep)
        g, v = optimize(table, cout, k, base + 400 + 100*j + rep, MS_STEPS, start=start)
        if v < v_best:
            best, v_best = g, v
    return best


def fit_job(family, base, tables, shapes):
    """One optimizer seed of one family: {layer: group}."""
    cal, search, steps = FAMILIES[family]
    out = {}
    for i, (name, j, k, cout) in enumerate(shapes):
        if search == 'fit_group':
            g, _ = fit_group(tables[name], cout, k, base + i, steps)
        else:
            g = multistart(tables[name], cout, k, j, base)
        out[name] = np.asarray(g, np.int64)
    return family, base, out


def layout_sums(n, groups, k, cout):
    """Summed W=4 window cycles of one layer for each of the layouts groups (L, C), from the per-window,
    per-channel nonzero counts n (N, C); the same rule as predict_w4.window_cycles (checked per image)."""
    groups = np.asarray(groups)
    nl, c = groups.shape
    m = np.zeros((c, nl*T), np.float32)
    m[np.tile(np.arange(c), nl), (np.arange(nl)[:, None]*T + groups).ravel()] = 1
    load, g = math.ceil(k/W) + 1, math.ceil(cout/P)
    out = np.zeros(nl, np.int64)
    for s in range(0, len(n), 8192):
        banks = (n[s:s + 8192].astype(np.float32) @ m).reshape(-1, nl, T).max(2).astype(np.int64)
        out += np.maximum(np.maximum(load, g*np.maximum(banks, 1)), cout).sum(0)
    return out


# ----------------------------------------------------------------------------- emulation

def counts_table(x, L):
    """(N, C_in) per window and channel the nonzero taps (C_in % 4 == 0: one residue)."""
    taps, cin = taps_and_channels(L)
    n = residue_counts(x, taps, cin)
    assert cin % T == 0 and not n[:, :, 1:].any(), L['name']
    return n[:, :, 0]


def calib_tables(set_name, image, noise_seed):
    """Per fitted layer, the full (N, 32) count table of one calibration image."""
    man, layers = run_denoise.load_layers(export_dir(MODEL))
    names = {L['name'] for L in fitted_layers(layers)}
    noisy = next(t[2] for t in test_noise(load_set(set_name), SIGMA, seed=noise_seed) if t[0] == image)
    tabs = {}

    def keep(L, x, acc):
        if L['name'] in names:
            tabs[L['name']] = counts_table(x, L)

    emulate(man, layers, np.rint(noisy*QMAX_A).astype(np.uint8), keep)
    return image, noise_seed, tabs


def init_eval(static_names, static_groups, checks):
    man, layers = run_denoise.load_layers(export_dir(MODEL))
    _STATE.update(man=man, layers=layers, names=static_names, groups=static_groups, checks=checks,
                  index={L['name']: i for i, L in enumerate(fitted_layers(layers))},
                  int_eval=json.loads((export_dir(MODEL)/'int_eval.json').read_text()),
                  tests={s: {n: (c, np.rint(q*QMAX_A).astype(np.uint8)) for n, c, q in
                             test_noise(load_set(s), SIGMA, seed=0)} for s in SETS})


def eval_image(set_name, name):
    """Per layer: original, bounds; per fitted layer the static layouts' and the dynamic layouts' counts."""
    st = _STATE
    clean, q_in = st['tests'][set_name][name]
    rng = np.random.default_rng(SEED)              # self-fitted oracle: fit.py's window draw, layer order
    per, self_groups, failed = {}, {}, []

    def hook(L, x, acc):
        k, cout = L['K'], L['COUT']
        load, g = math.ceil(k/W) + 1, math.ceil(cout/P)
        nnz = (x != 0).sum(1)
        rec = dict(original=int(window_cycles(x, k, cout, W).sum()),
                   perfect_balance=int(np.maximum(np.maximum(load, g*np.maximum(-(-nnz//T), 1)), cout).sum()),
                   floor=int(len(x))*max(load, cout))
        if not rec['floor'] <= rec['perfect_balance'] <= rec['original']:
            failed.append(f'{L["name"]}: bounds out of order')
        if L['name'] in st['groups']:
            taps, cin = taps_and_channels(L)
            n = counts_table(x, L)
            sums = layout_sums(n, st['groups'][L['name']], k, cout)
            ifm = (x[:, CENTER*cin:(CENTER + 1)*cin] != 0).sum(0)     # centre tap: every pixel once
            sel = rng.choice(len(x), size=min(SAMPLE, len(x)), replace=False)
            g_self, _ = fit_group(n[sel], cout, k, SEED + st['index'][L['name']], STEPS)
            self_groups[L['name']] = np.asarray(g_self).tolist()
            dyn = dict(sense_rr=deal(ifm, round_robin(cin)), sense_snake=deal(ifm, snake(cin)), sense_lpt=lpt(ifm),
                       window_greedy_self=np.asarray(g_self, np.int64))
            dsums = layout_sums(n, np.stack([dyn[d] for d in DYNAMIC]), k, cout)
            want = {'identity': rec['original']}
            for lay in st['checks']:
                order = order_from_group(st['groups'][L['name']][st['names'].index(lay)])
                want[lay] = int(window_cycles(x[:, permuted_columns(order, taps)], k, cout, W).sum())
            for lay, v in want.items():
                if int(sums[st['names'].index(lay)]) != v:
                    failed.append(f'{L["name"]} {lay}: fast count differs from window_cycles')
            xs = x[:, permuted_columns(order_from_group(dyn['sense_rr']), taps)]
            if int(window_cycles(xs, k, cout, W).sum()) != int(dsums[0]):
                failed.append(f'{L["name"]} sense_rr: fast count differs from window_cycles')
            if min(sums.min(), dsums.min()) < rec['perfect_balance']:
                failed.append(f'{L["name"]}: a layout counts below the perfect-balance bound')
            rec['static'] = sums.tolist()
            rec['dynamic'] = dict(zip(DYNAMIC, map(int, dsums)))
        per[L['name']] = rec

    out = emulate(st['man'], st['layers'], q_in, hook)
    p = float(psnr(clean, out.astype(np.float32)/255))
    psnr_ok = abs(p - st['int_eval'][set_name]['per_image'][name]) <= 1e-5
    return set_name, name, per, self_groups, psnr_ok, failed


# ----------------------------------------------------------------------------- summaries

def pct(a, b):
    return 100*(a - b)/a


def stats(orig, lay, bound, orig29=None, lay29=None):
    """orig, lay, bound: per-image totals (arrays) over one evaluation set."""
    s = pct(orig, lay)
    out = dict(pooled_pct=round(float(pct(orig.sum(), lay.sum())), 4),
               min_pct=round(float(s.min()), 4), median_pct=round(float(np.median(s)), 4),
               max_pct=round(float(s.max()), 4), images_saving_le_0=int((s <= 0).sum()),
               headroom_captured_pct=round(float(100*(orig.sum() - lay.sum())/(orig.sum() - bound.sum())), 2))
    if orig29 is not None:
        out['pooled_pct_conv2_9'] = round(float(pct(orig29.sum(), lay29.sum())), 4)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--out', type=Path, default=HERE/'baselines.json')
    ap.add_argument('--limit', type=int, default=0, help='test run: only the first N images of each set')
    args = ap.parse_args()
    t0 = time.time()
    man, layers = run_denoise.load_layers(export_dir(MODEL))
    assert man['sigma'] == SIGMA and check_im2col_order()      # centre tap s = 4 is the window's own pixel
    fit = fitted_layers(layers)
    fnames = [L['name'] for L in fit]
    shapes = [(L['name'], [M['name'] for M in layers].index(L['name']), L['K'], L['COUT']) for L in fit]
    by_name = {L['name']: L for L in fit}
    checks = {}

    # ---- calibration data
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        got = {(im, s): t for im, s, t in pool.map(calib_tables, ['Set12']*6,
                                                    [im for s in C3_NOISE_SEEDS for im in C3_IMAGES],
                                                    [s for s in C3_NOISE_SEEDS for im in C3_IMAGES])}
    rng = np.random.default_rng(SEED)
    c1 = {}
    for name in fnames:                                  # fit.py: one generator, layer order
        tab = got[(CALIB[1], 0)][name]
        c1[name] = tab[rng.choice(len(tab), size=min(SAMPLE, len(tab)), replace=False)]
    c3 = {}
    for name in fnames:                                  # q1_gpu_deadline_suite.load_or_fit
        parts = []
        for s in C3_NOISE_SEEDS:
            for im in C3_IMAGES:
                tab = got[(im, s)][name]
                r = np.random.default_rng(s*1000 + int(name[4:]))
                parts.append(tab[r.choice(len(tab), size=min(C3_WINDOWS, len(tab)), replace=False)])
        c3[name] = np.concatenate(parts)
    cal = dict(C1=c1, C3=c3)
    print(f'calibration windows per layer: C1 {len(c1[fnames[0]])}, C3 {len(c3[fnames[0]])}  '
          f'({time.time() - t0:.0f} s)', flush=True)

    # ---- layouts
    static = {'identity': {n: round_robin(32) for n in fnames}}
    for tag, data in (('', c1), ('_c3', c3)):
        d = {n: density_layouts(data[n]) for n in fnames}
        for m in ('density_rr', 'density_snake', 'meannnz_lpt'):
            static[m + tag] = {n: d[n][m] for n in fnames}
    rnd = random_layouts(fit)
    for r in range(N_RANDOM):
        static[f'random_{r:02d}'] = rnd[r]
    pub = json.loads(PUBLISHED.read_text())
    assert pub['model'] == MODEL
    static['frozen_published'] = {n: group_from_order(pub['orders'][by_name[n]['inputs'][0]]) for n in fnames}
    ms = {e['layer']: np.asarray(e['group_of_original_channel'], np.int64)
          for e in json.loads(MULTI_JSON.read_text())['layers']}
    static['multistart_published'] = {n: ms[n] for n in fnames}
    for key, zpath in (('frozen_published', ZIPS['frozen']), ('multistart_published', ZIPS['multistart'])):
        with zipfile.ZipFile(zpath) as z:
            orders = json.loads(z.read(f'{MODEL}/permutation_manifest.json'))['orders']
        checks[f'{key}_equals_zip_permutation_manifest'] = all(
            np.array_equal(group_from_order(orders[by_name[n]['inputs'][0]]), static[key][n]) for n in fnames)

    t1 = time.time()
    jobs = [(f, b) for f in FAMILIES for b in OPT_SEEDS]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(fit_job, f, b, cal[FAMILIES[f][0]], shapes) for f, b in jobs]
        for fut in concurrent.futures.as_completed(futs):
            f, b, groups = fut.result()
            static[f'{f}_s{b}'] = groups
    print(f'fitted {len(jobs)} family-seed layouts ({time.time() - t1:.0f} s)', flush=True)
    for key, fam in (('frozen_published', 'frozen_recipe_c1_s42'), ('multistart_published', 'multistart_c3_s42')):
        checks[f'{key}_reproduced_by_{fam}'] = all(np.array_equal(static[key][n], static[fam][n]) for n in fnames)
    for lay, groups in static.items():
        for n in fnames:
            assert sorted(np.bincount(groups[n], minlength=T).tolist()) == [8]*T, (lay, n)

    # calibration objective of every static layout: sum over the fitted layers of the mean W=4 window cycles
    cal_obj = {lay: {c: round(float(sum(cycles(cal[c][n], by_name[n]['COUT'], by_name[n]['K'], groups[n]).mean()
                                        for n in fnames)), 4) for c in cal} for lay, groups in static.items()}
    rand_names = [f'random_{r:02d}' for r in range(N_RANDOM)]
    best_cal = {c: min(rand_names, key=lambda r: cal_obj[r][c]) for c in cal}

    # ---- evaluation
    names = list(static)
    groups_by_layer = {n: np.stack([static[lay][n] for lay in names]) for n in fnames}
    t2 = time.time()
    rows = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs, initializer=init_eval,
                                                initargs=(names, groups_by_layer,
                                                          ('frozen_published', 'multistart_published',
                                                           'random_00'))) as pool:
        imgs = [(s, n) for s in SETS for n, _ in load_set(s)[:args.limit or None]]
        futs = [pool.submit(eval_image, s, n) for s, n in imgs]
        for i, fut in enumerate(concurrent.futures.as_completed(futs)):
            s, n, per, self_groups, psnr_ok, failed = fut.result()
            rows[(s, n)] = (per, self_groups, psnr_ok, failed)
            print(f'{i + 1:>2}/{len(imgs)} {s:<6}{n:<12} {time.time() - t2:5.0f} s', flush=True)

    # ---- per-image totals
    ref = json.loads((ROOT/'denoise'/'test_set_counts.json').read_text())['networks'][LABEL]
    assert ref['model'] == MODEL
    b32 = HERE/'b32_testsets.json'
    b32 = {(r['set'], r['image']): r['w4'] for r in json.loads(b32.read_text())['images']} if b32.exists() else None
    fails, psnr_ok, ref_ok, b32_ok = [], 0, 0, 0
    tot = {}
    for (s, n) in imgs:
        per, self_groups, ok, failed = rows[(s, n)]
        fails += [f'{s} {n} {f}' for f in failed]
        psnr_ok += ok
        orig = sum(r['original'] for r in per.values())
        fixed = orig - sum(per[f]['original'] for f in fnames)          # conv1 + conv10
        t = dict(original=orig, perfect_balance=sum(r['perfect_balance'] for r in per.values()),
                 floor=sum(r['floor'] for r in per.values()), fixed=fixed)
        for li, lay in enumerate(names):
            t[lay] = fixed + sum(per[f]['static'][li] for f in fnames)
        for d in DYNAMIC:
            t[d] = fixed + sum(per[f]['dynamic'][d] for f in fnames)
        t['per_layer'] = {f: dict(original=per[f]['original'], perfect_balance=per[f]['perfect_balance'],
                                  **{lay: per[f]['static'][li] for li, lay in enumerate(names)},
                                  **per[f]['dynamic']) for f in fnames}
        tot[(s, n)] = t
        ref_ok += orig == ref['sets'][s]['per_image'][n]['sparse_w4']
        if b32 is not None:
            b32_ok += (b32[(s, n)]['original'] == orig and b32[(s, n)]['frozen'] == t['frozen_published']
                       and b32[(s, n)]['multistart'] == t['multistart_published'])
        if (s, n) == ('Set12', CALIB[1]):
            checks['self_fitted_oracle_on_01_equals_frozen'] = all(
                self_groups[f] == static['frozen_published'][f].tolist() for f in fnames)
    checks.update(images=len(imgs), psnr_equals_int_eval=f'{psnr_ok}/{len(imgs)}',
                  original_counts_equal_test_set_counts=f'{ref_ok}/{len(imgs)}',
                  fast_counts_equal_window_cycles_and_bounds_hold=not fails, failures=fails[:20])
    checks['published_counts_equal_b32_testsets'] = (f'{b32_ok}/{len(imgs)}' if b32 is not None else
                                                     'bankperm/b32_testsets.json not present')

    # ---- summaries
    def arr(keys, lay, layer=None):
        if layer is None:
            return np.array([tot[k][lay] for k in keys], np.float64)
        return np.array([tot[k]['per_layer'][layer][lay] for k in keys], np.float64)

    def arr29(keys, lay):
        return np.array([tot[k][lay] - tot[k]['fixed'] for k in keys], np.float64)

    def method_stats(keys, lay):
        return stats(arr(keys, 'original'), arr(keys, lay), arr(keys, 'perfect_balance'),
                     arr29(keys, 'original'), arr29(keys, lay))

    cal_of = {lay: ('C3' if lay.endswith('_c3') or '_c3_' in lay or lay == 'multistart_published' else
                    'C1' if lay != 'identity' and not lay.startswith('random_') else None) for lay in names}
    summary, families = {}, {}
    for es, keep in EVAL_SETS.items():
        keys = [k for k in imgs if keep(*k)]
        o, b = arr(keys, 'original'), arr(keys, 'perfect_balance')
        rec = dict(images=len(keys), original_cycles=int(o.sum()),
                   perfect_balance=dict(cycles=int(b.sum()), **{k: v for k, v in stats(o, b, b).items()
                                                               if k != 'headroom_captured_pct'}),
                   floor=dict(cycles=int(arr(keys, 'floor').sum()),
                              **{k: v for k, v in stats(o, arr(keys, 'floor'), b).items()
                                 if k != 'headroom_captured_pct'}),
                   methods={})
        single = ['identity', 'density_rr', 'density_snake', 'meannnz_lpt', 'density_rr_c3', 'density_snake_c3',
                  'meannnz_lpt_c3', 'frozen_published', 'multistart_published']
        for lay in single:
            rec['methods'][lay] = dict(calibration=cal_of[lay], clean=not (es == '79' and cal_of[lay] == 'C3'),
                                       **method_stats(keys, lay))
        for lay in DYNAMIC:
            rec['methods'][lay] = dict(calibration='self', deployable=False,
                                       **method_stats(keys, lay))
        # random layouts
        rand = np.stack([arr(keys, r) for r in rand_names])                 # (20, images)
        pooled = np.array([pct(o.sum(), rand[r].sum()) for r in range(N_RANDOM)])
        med = np.median(rand, 0)
        rec['methods']['random_median'] = dict(
            what='median over the 20 layouts of the pooled saving; per-image figures from the per-image median',
            pooled_pct=round(float(np.median(pooled)), 4), pooled_range_of_20=[round(float(pooled.min()), 4),
                                                                              round(float(pooled.max()), 4)],
            **{k: v for k, v in stats(o, med, b).items() if k != 'pooled_pct'})
        for c in cal:
            lay = best_cal[c]
            rec['methods'][f'random_best_cal_{c.lower()}'] = dict(layout=lay, calibration=c, deployable=True,
                                                                 clean=not (es == '79' and c == 'C3'),
                                                                 **method_stats(keys, lay))
        rec['methods']['random_oracle'] = dict(
            what='best of the 20 layouts per test image (selected on the evaluation image)', deployable=False,
            **stats(o, rand.min(0), b))
        for fam, (c, search, steps) in FAMILIES.items():
            per_seed = {str(sd): method_stats(keys, f'{fam}_s{sd}') for sd in OPT_SEEDS}
            pv = np.array([v['pooled_pct'] for v in per_seed.values()])
            hv = np.array([v['headroom_captured_pct'] for v in per_seed.values()])
            evals = BUDGET if search == 'multistart' else steps + 1
            rec['methods'][fam] = dict(calibration=c, search=search, objective_evaluations_per_layer=evals,
                                       clean=not (es == '79' and c == 'C3'),
                                       pooled_pct_mean=round(float(pv.mean()), 4),
                                       pooled_pct_min=round(float(pv.min()), 4),
                                       pooled_pct_max=round(float(pv.max()), 4),
                                       headroom_captured_pct_mean=round(float(hv.mean()), 2),
                                       per_seed=per_seed)
        summary[es] = rec

    # per-layer pooled saving over the 79
    keys79 = [k for k in imgs if EVAL_SETS['79'](*k)]
    per_layer = {}
    for f in fnames:
        o, b = arr(keys79, 'original', f), arr(keys79, 'perfect_balance', f)
        row = dict(perfect_balance=round(float(pct(o.sum(), b.sum())), 3))
        for lay in ('density_rr', 'density_snake', 'meannnz_lpt', 'sense_rr', 'sense_lpt', 'window_greedy_self',
                    'frozen_published', 'greedy_budget_c1_s42', 'multistart_published'):
            row[lay] = round(float(pct(o.sum(), arr(keys79, lay, f).sum())), 3)
        per_layer[f] = row

    # density statistic vs window-level objective
    m79, m77 = summary['79']['methods'], summary['77']['methods']
    dens79 = max(('density_rr', 'density_snake', 'meannnz_lpt'), key=lambda m: m79[m]['pooled_pct'])
    dens77 = max(('density_rr_c3', 'density_snake_c3', 'meannnz_lpt_c3'), key=lambda m: m77[m]['pooled_pct'])
    sense79 = max(('sense_rr', 'sense_snake', 'sense_lpt'), key=lambda m: m79[m]['pooled_pct'])
    ratio = lambda a, b: round(100*a/b, 1)
    dvw = {
        'C1 static, 79 images': dict(
            best_density=dens79, best_density_pooled_pct=m79[dens79]['pooled_pct'],
            frozen_recipe_mean_of_5_seeds_pooled_pct=m79['frozen_recipe_c1']['pooled_pct_mean'],
            greedy_budget_mean_of_5_seeds_pooled_pct=m79['greedy_budget_c1']['pooled_pct_mean'],
            density_share_of_frozen_recipe_pct=ratio(m79[dens79]['pooled_pct'],
                                                     m79['frozen_recipe_c1']['pooled_pct_mean']),
            density_share_of_greedy_budget_pct=ratio(m79[dens79]['pooled_pct'],
                                                     m79['greedy_budget_c1']['pooled_pct_mean'])),
        'C3 static, 77 images': dict(
            best_density=dens77, best_density_pooled_pct=m77[dens77]['pooled_pct'],
            greedy_budget_mean_of_5_seeds_pooled_pct=m77['greedy_budget_c3']['pooled_pct_mean'],
            multistart_mean_of_5_seeds_pooled_pct=m77['multistart_c3']['pooled_pct_mean'],
            density_share_of_greedy_budget_pct=ratio(m77[dens77]['pooled_pct'],
                                                     m77['greedy_budget_c3']['pooled_pct_mean']),
            density_share_of_multistart_pct=ratio(m77[dens77]['pooled_pct'], m77['multistart_c3']['pooled_pct_mean'])),
        'per image, 79 images (oracles, not deployable)': dict(
            best_sense_like=sense79, best_sense_like_pooled_pct=m79[sense79]['pooled_pct'],
            window_greedy_self_pooled_pct=m79['window_greedy_self']['pooled_pct'],
            sense_share_of_window_self_pct=ratio(m79[sense79]['pooled_pct'], m79['window_greedy_self']['pooled_pct']),
            sense_share_of_frozen_recipe_pct=ratio(m79[sense79]['pooled_pct'],
                                                   m79['frozen_recipe_c1']['pooled_pct_mean'])),
    }

    per_image = {}
    for (s, n) in imgs:
        t = tot[(s, n)]
        e = {k: int(t[k]) for k in ('original', 'perfect_balance', 'floor', 'density_rr', 'density_snake',
                                    'meannnz_lpt', 'density_rr_c3', 'density_snake_c3', 'meannnz_lpt_c3',
                                    'frozen_published', 'multistart_published') + DYNAMIC}
        rv = [t[r] for r in rand_names]
        e.update(random_median=float(np.median(rv)), random_best=int(min(rv)),
                 random_best_cal_c1=int(t[best_cal['C1']]), random_best_cal_c3=int(t[best_cal['C3']]))
        for fam in FAMILIES:
            e[fam] = [int(t[f'{fam}_s{sd}']) for sd in OPT_SEEDS]
        per_image[f'{s}/{n}'] = e

    res = dict(
        network=LABEL, model=MODEL, protocol='bankperm/PROTOCOL.md',
        count=('W=4 sparse window cycles, max(ceil(K/4)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT), summed over '
               'conv1-conv10 (predict_w4.window_cycles); fill and drain left out; conv1 and conv10 are the same in '
               'every layout'),
        images='Set12 + BSD68, sigma 25, test_noise seed 0, host emulation of the original export',
        saving='100 * (original - layout) / original; pooled over the summed counts of the images',
        headroom='headroom_captured_pct = 100 * (original - layout) / (original - perfect balance), pooled',
        evaluation_sets={'79': 'all 80 but Set12 01.png (C1)', '77': 'all 80 but Set12 01-03 (C3)'},
        calibrations=dict(
            C1=dict(what='Set12 01.png, noise seed 0, one default_rng(42) in layer order (fit.py, PROTOCOL.md)',
                    windows_per_layer=int(len(c1[fnames[0]]))),
            C3=dict(what=('Set12 01/02/03, noise seeds 0 and 1, per image, seed and layer default_rng(seed*1000 + '
                          'layer number) (q1_gpu_deadline_suite.load_or_fit, Multi-start\'s data)'),
                    windows_per_layer=int(len(c3[fnames[0]])))),
        budget=dict(
            multistart=('greedy from the identity + 4 greedies from balanced random starts, 400 proposals each, '
                        'best kept (q1_gpu_deadline_suite defaults: --greedy-steps 400 --restarts 4)'),
            objective_evaluations_per_layer=BUDGET,
            counting='each start\'s first evaluation counted, as in q1_fair_budget.py',
            frozen_recipe=f'fit_group, {STEPS} proposals = {STEPS + 1} evaluations',
            equal_budget_greedy=f'fit_group, {BUDGET - 1} proposals = {BUDGET} evaluations',
            optimizer_seeds=list(OPT_SEEDS),
            seeds=('fit_group: seed + fitted-layer index (conv2 -> 0); Multi-start: q1_gpu_deadline_suite --seed '
                   '<seed> (its per-layer seeds from the layer index, conv2 -> 1)')),
        methods_not_deployable=('sense_rr, sense_snake, sense_lpt need the image\'s maps before the layer runs '
                                '(run-time ranking hardware, not on this core); window_greedy_self is fitted on '
                                'the test image; random_oracle is chosen per test image'),
        multistart_selection=('the published Multi-start was calibrated on Set12 01-03 and chosen for the board '
                              'after its BSD68 results were seen (best of 6 methods); its 77-image figure is not '
                              'used to choose anything here, but the choice of that method was made on BSD68'),
        calibration_objective=dict(what='sum over conv2-conv9 of the mean W=4 window cycles on the calibration '
                                        'windows', identity=cal_obj['identity'],
                                   **{k: cal_obj[k] for k in ('density_rr', 'density_snake', 'meannnz_lpt',
                                                              'density_rr_c3', 'density_snake_c3',
                                                              'meannnz_lpt_c3', 'frozen_published',
                                                              'multistart_published')},
                                   random_best=dict(C1=[best_cal['C1'], cal_obj[best_cal['C1']]],
                                                    C3=[best_cal['C3'], cal_obj[best_cal['C3']]]),
                                   **{fam: {str(sd): cal_obj[f'{fam}_s{sd}'] for sd in OPT_SEEDS}
                                      for fam in FAMILIES}),
        checks=checks, summary=summary, per_layer_pooled_79=per_layer, density_vs_window=dvw,
        per_image=per_image, seconds=round(time.time() - t0))
    if args.limit:
        res['partial'] = f'test run: first {args.limit} images of each set only'
    write_json(args.out, res)

    print(f'\n{"method":<26}{"cal":>4} {"pooled":>7} {"min":>7} {"median":>7} {"max":>7} {"headroom":>8}'
          '   (79 images; 77 images)')
    for lay, v in summary['79']['methods'].items():
        w = summary['77']['methods'][lay]
        if 'per_seed' in v:
            print(f'{lay:<26}{v["calibration"]:>4} mean {v["pooled_pct_mean"]:6.3f} [{v["pooled_pct_min"]:.3f}, '
                  f'{v["pooled_pct_max"]:.3f}] hr {v["headroom_captured_pct_mean"]:5.1f}%   '
                  f'77: {w["pooled_pct_mean"]:6.3f} [{w["pooled_pct_min"]:.3f}, {w["pooled_pct_max"]:.3f}]')
        else:
            print(f'{lay:<26}{str(v.get("calibration", "-"))[:4]:>4} {v["pooled_pct"]:7.3f} {v["min_pct"]:7.3f} '
                  f'{v["median_pct"]:7.3f} {v["max_pct"]:7.3f} {v["headroom_captured_pct"]:7.1f}%   '
                  f'77: {w["pooled_pct"]:7.3f} hr {w["headroom_captured_pct"]:5.1f}%')
    for es in EVAL_SETS:
        print(es, 'perfect balance', summary[es]['perfect_balance']['pooled_pct'], 'floor',
              summary[es]['floor']['pooled_pct'])
    print('density vs window', json.dumps(dvw, indent=1))
    print('checks', json.dumps({k: v for k, v in checks.items() if k != 'failures'}), checks['failures'][:5])
    print(f'wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out.name} '
          f'in {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
