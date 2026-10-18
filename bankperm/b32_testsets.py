"""Original vs Frozen vs Multi-start layouts of B-32 ReLU + QAT s1 on all 80 test images.

    python bankperm/b32_testsets.py [--jobs 2] [--frozen ZIP] [--multi ZIP]
                                    # writes bankperm/b32_testsets.json

For every Set12 and BSD68 image (sigma 25, test_noise seed 0, as int_eval)
this runs the board driver's host emulation of each of the three exports (the
Original in the tree; the Frozen and Multi-start ones read from their ZIPs as
in bankperm/b32_board.py) and counts every layer's windows at W = 1, 2, 4
(denoise/predict_w4.window_cycles, sparse mode; fill and drain left out, as in
denoise/count_test_sets.py). The permuted layouts' windows are those of their
own emulation, on every image. Per image it keeps the conv1-conv10 totals, the
conv2-conv9 W=4 total and the layers whose W=4 count a permuted layout raises.

It also checks, on every image:
  - the denoised images of the three layouts are identical;
  - each layer's windows of a permuted layout are the Original's with the
    columns permuted by the export's permutation_manifest.json (tap s*C + j of
    the permuted layout is tap s*C + order[j] of the Original, order that of
    the layer the channel comes from; image channels are not permuted), and
    counting those column-permuted windows gives the same counts;
  - the Original's counts equal denoise/test_set_counts.json (B-32 ReLU + QAT s1).

Summaries of the per-image saving (range, median, mean, pooled over the
images' summed counts) over all 80 images, the 79 without 01.png (Frozen's
calibration image; the protocol's headline set), the 77 without Set12 01-03
(Multi-start's calibration images), and per set; the rank of 05.png; the
image-layers where a permuted layout counts more than the Original.
"""
import argparse
import concurrent.futures
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from b32_board import LAYOUTS, MODEL, WIDTHS, ZIPS, counts, emulate, layouts, pct, rel  # noqa: E402

SETS = ('Set12', 'BSD68')
CAL_MULTI = {'01.png', '02.png', '03.png'}
SUBSETS = {
    'all 80': lambda s, n: True,
    '79 without 01.png': lambda s, n: not (s == 'Set12' and n == '01.png'),
    '77 without Set12 01-03': lambda s, n: not (s == 'Set12' and n in CAL_MULTI),
    'Set12': lambda s, n: s == 'Set12',
    'BSD68': lambda s, n: s == 'BSD68',
    'Set12 01-03': lambda s, n: s == 'Set12' and n in CAL_MULTI,
}
METRICS = ('w1', 'w2', 'w4', 'w4_conv2_9')
_STATE = {}


def column_order(L, by_name, orders):
    """For layer L of a permuted layout, the Original's tap at each of its taps."""
    taps = L['kh']*L['kw']
    cin = L['K']//taps
    assert cin*taps == L['K'], L['name']
    sizes = {s: by_name[s]['COUT']//(2 if by_name[s]['post'] in ('maxout', 'avg') else 1)
             for s in L['inputs'] if s != 'image'}
    if 'image' in L['inputs']:
        sizes['image'] = cin - sum(sizes.values())
    chan, off = [], 0
    for s in L['inputs']:
        order = orders.get(s, list(range(sizes[s])))
        assert sorted(order) == list(range(sizes[s])), (L['name'], s)
        chan += [off + c for c in order]
        off += sizes[s]
    assert off == cin, L['name']
    return (np.arange(taps)[:, None]*cin + np.asarray(chan)[None, :]).ravel()


def init(dirs):
    """Per worker: the three layouts' layers and permutation orders, and the noisy test images."""
    st = {}
    for n, d in dirs.items():
        man, layers = run_denoise.load_layers(Path(d))
        f = Path(d)/'permutation_manifest.json'
        orders = json.loads(f.read_text())['orders'] if n != 'original' else {}
        st[n] = (man, layers, orders)
    sigma = st['original'][0]['sigma']
    _STATE.update(layouts=st, sigma=sigma, tests={
        s: {name: np.rint(noisy*QMAX_A).astype(np.uint8) for name, clean, noisy in test_noise(load_set(s), sigma, seed=0)}
        for s in SETS})


def one_image(set_name, name):
    """Per-layer counts of the three layouts on one image, and the checks."""
    q_in = _STATE['tests'][set_name][name]
    per = {n: [] for n in LAYOUTS}
    orig = {}

    def keep(L, x):
        orig[L['name']] = x
        per['original'].append(dict(name=L['name'], windows=int(x.shape[0]), **counts(x, L['K'], L['COUT'])))

    man, layers, _ = _STATE['layouts']['original']
    out0 = emulate(man, layers, q_in, keep)
    checks = {}
    for n in LAYOUTS[1:]:
        man, layers, orders = _STATE['layouts'][n]
        by_name = {L['name']: L for L in layers}
        same_windows, same_counts = [], []

        def check(L, x):
            c = counts(x, L['K'], L['COUT'])
            xo = orig[L['name']][:, column_order(L, by_name, orders)]
            same_windows.append(bool(np.array_equal(x, xo)))
            same_counts.append(counts(xo, L['K'], L['COUT']) == c)
            per[n].append(dict(name=L['name'], windows=int(x.shape[0]), **c))

        out = emulate(man, layers, q_in, check)
        checks[n] = dict(denoised_identical=bool(np.array_equal(out, out0)),
                         windows_are_column_permutation=all(same_windows) and len(same_windows) == len(orig),
                         column_permuted_counts_equal=all(same_counts) and len(same_counts) == len(orig))
    return set_name, name, per, checks


def summarize(images, keep):
    sel = [r for r in images if keep(r['set'], r['image'])]
    out = dict(images=len(sel))
    for n in LAYOUTS[1:]:
        d = {}
        for m in METRICS:
            s = np.array([r['saving_pct'][n][m] for r in sel])
            a, b = sum(r[m]['original'] for r in sel), sum(r[m][n] for r in sel)
            d[m] = dict(min=round(float(s.min()), 4), max=round(float(s.max()), 4), median=round(float(np.median(s)), 4),
                        mean=round(float(s.mean()), 4), pooled=pct(a, b))
        d['images_with_w4_saving_le_0'] = sum(r['saving_pct'][n]['w4'] <= 0 for r in sel)
        d['image_layers_worse_w4'] = sum(len(r['worse_layers_w4'][n]) for r in sel)
        d['image_layers'] = 10*len(sel)
        out[n] = d
    out['multistart_below_frozen_w4'] = sum(r['w4']['multistart'] < r['w4']['frozen'] for r in sel)
    out['frozen_below_multistart_w4'] = sum(r['w4']['frozen'] < r['w4']['multistart'] for r in sel)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--frozen', type=Path, default=ZIPS['frozen'], help='Frozen export ZIP')
    ap.add_argument('--multi', type=Path, default=ZIPS['multistart'], help='Multi-start export ZIP')
    ap.add_argument('--out', type=Path, default=HERE/'b32_testsets.json')
    args = ap.parse_args()
    t0 = time.time()
    names = {s: [n for n, _ in load_set(s)] for s in SETS}
    with tempfile.TemporaryDirectory() as tmp:
        lay = layouts({'frozen': args.frozen, 'multistart': args.multi}, tmp)
        dirs = {n: str(lay[n][1]) for n in LAYOUTS}
        got = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs, initializer=init, initargs=(dirs,)) as pool:
            futs = [pool.submit(one_image, s, n) for s in SETS for n in names[s]]
            for i, fut in enumerate(concurrent.futures.as_completed(futs)):
                s, n, per, checks = fut.result()
                got[(s, n)] = (per, checks)
                print(f'{i+1:>2}/{len(futs)} {s:<6}{n:<12} W4 ' + '  '.join(
                    f'{k} {sum(r["w4"] for r in per[k]):>11,}' for k in LAYOUTS) + f'  {time.time()-t0:5.0f} s', flush=True)

    ref = json.loads((ROOT/'denoise'/'test_set_counts.json').read_text())
    ref = next(v for v in ref['networks'].values() if v['model'] == MODEL)['sets']
    images, check_fail = [], []
    tally = {n: dict(denoised_identical=0, windows_are_column_permutation=0, column_permuted_counts_equal=0)
             for n in LAYOUTS[1:]}
    ref_ok = w12_layers = 0
    for s in SETS:
        for n in names[s]:
            per, checks = got[(s, n)]
            rec = dict(set=s, image=n, windows=sum(r['windows'] for r in per['original']))
            for w in WIDTHS:
                rec[f'w{w}'] = {k: sum(r[f'w{w}'] for r in per[k]) for k in LAYOUTS}
            rec['w4_conv2_9'] = {k: sum(r['w4'] for r in per[k][1:9]) for k in LAYOUTS}
            rec['saving_pct'] = {k: {m: pct(rec[m]['original'], rec[m][k]) for m in METRICS} for k in LAYOUTS[1:]}
            rec['worse_layers_w4'] = {k: {a['name']: pct(a['w4'], b['w4']) for a, b in zip(per['original'], per[k])
                                          if b['w4'] > a['w4']} for k in LAYOUTS[1:]}
            images.append(rec)
            for k in LAYOUTS[1:]:
                w12_layers += sum(a[f'w{w}'] != b[f'w{w}'] for a, b in zip(per['original'], per[k]) for w in (1, 2))
                for c, v in checks[k].items():
                    tally[k][c] += v
                    if not v:
                        check_fail.append(f'{s} {n} {k} {c}')
            r = ref[s]['per_image'][n]
            ok = all(rec[f'w{w}']['original'] == r[f'sparse_w{w}'] for w in WIDTHS)
            ref_ok += ok
            if not ok:
                check_fail.append(f'{s} {n} original counts differ from denoise/test_set_counts.json')

    s4 = {k: [(r['saving_pct'][k]['w4'], r['set'], r['image']) for r in images] for k in LAYOUTS[1:]}
    rank05 = {}
    for k, v in s4.items():
        mine = next(x[0] for x in v if x[1] == 'Set12' and x[2] == '05.png')
        rank05[k] = dict(saving_w4_pct=mine, rank_from_smallest_saving=1 + sum(x[0] < mine for x in v),
                         rank_from_largest_saving=1 + sum(x[0] > mine for x in v), of=len(v))
    nimg = len(images)
    res = dict(
        model=MODEL, noise='Set12 + BSD68, sigma 25 (the manifest\'s), test_noise seed 0 (as int_eval)',
        count_rule=('window = max(ceil(K/W)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT), summed over conv1-conv10 '
                    '(denoise/predict_w4.window_cycles, sparse); fill and drain left out'),
        saving='100 * (Original - layout) / Original of the count; pooled = over the summed counts of the images',
        sources={n: rel(src) for n, (src, _) in lay.items()},
        how=('every layout\'s windows come from the host emulation of its own export on every image; the '
             'column-permutation check below compares them with the Original\'s windows permuted by the export\'s '
             'permutation_manifest.json'),
        checks=dict(images=nimg,
                    per_layout={k: {c: f'{v}/{nimg}' for c, v in t.items()} for k, t in tally.items()},
                    original_counts_equal_denoise_test_set_counts=f'{ref_ok}/{nimg} images ({3*ref_ok} counts)',
                    image_layers_where_w1_or_w2_count_differs=w12_layers,
                    failures=check_fail),
        summaries={label: summarize(images, keep) for label, keep in SUBSETS.items()},
        rank_of_05=rank05,
        images=images)
    args.out.write_text(json.dumps(res, indent=1) + '\n')
    for label, sm in res['summaries'].items():
        print(f'{label:<24} n={sm["images"]:>2}  ' + '  '.join(
            f'{k}: W4 {sm[k]["w4"]["min"]:.2f}..{sm[k]["w4"]["max"]:.2f}% median {sm[k]["w4"]["median"]:.2f} '
            f'pooled {sm[k]["w4"]["pooled"]:.2f} (W1 {sm[k]["w1"]["pooled"]:.2f}, W2 {sm[k]["w2"]["pooled"]:.2f}; '
            f'worse layers {sm[k]["image_layers_worse_w4"]})' for k in LAYOUTS[1:]))
    print('05.png', rank05)
    print('checks', res['checks'])
    print(f'wrote {rel(args.out)} in {time.time()-t0:.0f} s')


if __name__ == '__main__':
    main()
