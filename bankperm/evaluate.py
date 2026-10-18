"""Count every test image on the original and the permuted layout of every network.

    python bankperm/evaluate.py [--jobs 2]      # writes bankperm/results.json (about an hour on 2 cores)

PROTOCOL.md's evaluation of the permutation of bankperm/perms.json (`orders`):
all 80 test images (Set12 and BSD68, sigma 25, test_noise seed 0), the board
driver's host emulation (scripts/run_denoise.py), and per image the per-window
count of predict_w4.window_cycles (sparse mode) summed over conv1-convL, at
W = 1, 2 and 4, for the original and the permuted layout.

The permuted network's windows are the original's with the input columns of
conv2 .. conv(L-1) permuted (column s*C_in + p reads original channel order[p]):
the activation values are relabelled, not changed. bankperm/fold.py checks
exactly this on exported permuted networks (fold_check.json); here the permuted
count is window_cycles on the column-permuted original windows, and on every
fitted layer of every image it is also checked against fit.py's fast objective.
Every image's denoised PSNR is checked against the export's int_eval.json.

Summaries per network and width, over the 79 images other than Set12 01.png
(the calibration image): per-image saving range and median, pooled saving,
images with saving <= 0, image-layers (fitted layers) that got worse, and the
pooled saving of each fitted layer; 05.png and 01.png separately; as context
only, the same split by Set12 and BSD68. Then the verdicts H1-H3 of PROTOCOL.md
against bankperm/bounds.json.
"""
import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from count_test_sets import MODELS, SETS  # noqa: E402
from predict_w4 import window_cycles  # noqa: E402
from fit import (emulate, export_dir, fast_cycles, fitted_layers, group_from_order, permuted_columns,  # noqa: E402
                 residue_counts, taps_and_channels, write_json)

WIDTHS = (1, 2, 4)
SIGMA = 25
CALIB, ALSO = ('Set12', '01.png'), ('Set12', '05.png')


def count_set(label, set_name, orders):
    """Per image: per layer the summed window cycles, original and permuted, at each width."""
    t0 = time.time()
    model = MODELS[label]
    man, layers = run_denoise.load_layers(export_dir(model))
    assert man['sigma'] == SIGMA, (model, man['sigma'])
    fit = {L['name']: np.asarray(orders[L['inputs'][0]]) for L in fitted_layers(layers)}
    int_eval = json.loads((export_dir(model)/'int_eval.json').read_text())[set_name]['per_image']
    per_image = {}
    for name, clean, noisy in test_noise(load_set(set_name), SIGMA, seed=0):
        rows = []

        def hook(L, x, acc):
            k, cout = L['K'], L['COUT']
            row = dict(name=L['name'])
            if L['name'] in fit:
                taps, cin = taps_and_channels(L)
                order = fit[L['name']]
                xp = x[:, permuted_columns(order, taps)]
                c4 = window_cycles(xp, k, cout, 4)
                if not np.array_equal(c4, fast_cycles(residue_counts(x, taps, cin), group_from_order(order), k, cout, 4)):
                    raise AssertionError(f'{label} {name} {L["name"]}: fast objective differs from window_cycles')
            for w in WIDTHS:
                o = int(window_cycles(x, k, cout, w).sum())
                p = (int(c4.sum()) if w == 4 else int(window_cycles(xp, k, cout, w).sum())) if L['name'] in fit else o
                row[f'w{w}'] = (o, p)
            rows.append(row)

        out = emulate(man, layers, np.rint(noisy*QMAX_A).astype(np.uint8), hook)
        p = float(psnr(clean, out.astype(np.float32)/255))
        per_image[name] = dict(psnr=p, psnr_matches_int_eval=abs(p - int_eval[name]) <= 1e-5, layers=rows)
    return label, set_name, per_image, time.time() - t0


def saving(o, p):
    return 100*(o - p)/o


def summary(imgs, w, fitted):
    """Range, median and pooled saving at width w over imgs = {key: per-image record}."""
    o = np.array([sum(r[f'w{w}'][0] for r in v['layers']) for v in imgs.values()], np.int64)
    p = np.array([sum(r[f'w{w}'][1] for r in v['layers']) for v in imgs.values()], np.int64)
    s = saving(o, p)
    worse = sum(r[f'w{w}'][1] > r[f'w{w}'][0] for v in imgs.values() for r in v['layers'] if r['name'] in fitted)
    return dict(images=len(imgs), min_pct=float(s.min()), median_pct=float(np.median(s)), max_pct=float(s.max()),
                pooled_pct=float(saving(o.sum(), p.sum())), original_cycles=int(o.sum()), permuted_cycles=int(p.sum()),
                images_saving_le_0=int((s <= 0).sum()), image_layers=len(imgs)*len(fitted),
                image_layers_worse=int(worse))


def network_summary(per_image, fitted):
    head = {k: v for k, v in per_image.items() if k != CALIB}
    out = {}
    for w in WIDTHS:
        rec = dict(headline_79=summary(head, w, fitted))
        for key, tag in ((ALSO, '05.png'), (CALIB, '01.png')):
            o, p = (sum(r[f'w{w}'][i] for r in per_image[key]['layers']) for i in (0, 1))
            rec[tag] = dict(original=o, permuted=p, saving_pct=saving(o, p))
        rec['per_layer_pooled_79'] = {}
        for n in fitted:
            o, p = (sum(r[f'w{w}'][i] for v in head.values() for r in v['layers'] if r['name'] == n) for i in (0, 1))
            rec['per_layer_pooled_79'][n] = dict(saving_pct=saving(o, p), worse_images=int(sum(
                r[f'w{w}'][1] > r[f'w{w}'][0] for v in head.values() for r in v['layers'] if r['name'] == n)))
        rec['context_by_set'] = {s: summary({k: v for k, v in head.items() if k[0] == s}, w, fitted) for s in SETS}
        out[f'w{w}'] = rec
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--networks', help='comma-separated labels (default: all ten; a subset is a test run)')
    ap.add_argument('--out', type=Path, default=HERE/'results.json')
    args = ap.parse_args()
    t0 = time.time()
    perms = json.loads((HERE/'perms.json').read_text())['networks']
    bounds = json.loads((HERE/'bounds.json').read_text())['networks']
    labels = args.networks.split(',') if args.networks else list(MODELS)
    raw = {label: {} for label in labels}
    secs = {label: 0.0 for label in labels}
    jobs = [(label, s) for s in reversed(SETS) for label in labels]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(count_set, label, s, perms[label]['orders']) for label, s in jobs]
        for fut in concurrent.futures.as_completed(futs):
            label, set_name, per_image, sec = fut.result()
            raw[label].update({(set_name, k): v for k, v in per_image.items()})
            secs[label] += sec
            print(f'{label:<26}{set_name:<6} {len(per_image)} images  {sec:6.0f} s', flush=True)

    res = dict(protocol='bankperm/PROTOCOL.md', orders='bankperm/perms.json networks.<label>.orders',
               images='Set12 (12) + BSD68 (68), sigma 25, test_noise seed 0, host emulation',
               count='sum over conv1-convL of predict_w4.window_cycles (sparse mode); fill and drain left out',
               headline='the 79 images other than Set12 01.png (the calibration image)',
               saving='100 * (original - permuted) / original', networks={})
    for label in labels:
        fitted = [L['layer'] for L in perms[label]['fitted']]
        per_image = raw[label]
        assert len(per_image) == 80, (label, len(per_image))
        rec = dict(model=MODELS[label], fitted_layers=fitted, can_pay=bounds[label]['can_pay'],
                   psnr_checks=f'{sum(v["psnr_matches_int_eval"] for v in per_image.values())}/80 match int_eval.json',
                   cpu_seconds=round(secs[label]), summary=network_summary(per_image, fitted))
        rec['per_image'] = {}
        for (s, n), v in sorted(per_image.items()):
            e = {f'w{w}': [sum(r[f'w{w}'][i] for r in v['layers']) for i in (0, 1)] for w in WIDTHS}
            for w in WIDTHS:
                worse = [r['name'] for r in v['layers'] if r[f'w{w}'][1] > r[f'w{w}'][0]]
                if worse:
                    e[f'worse_layers_w{w}'] = worse
            rec['per_image'][f'{s}/{n}'] = e
        # H1 per layer, as context: every layer bounds.py calls unable to pay is unchanged on every image.
        cannot = {w: {r['name'] for r in bounds[label]['layers'] if not r[f'can_pay_w{w}']} for w in WIDTHS}
        rec['layers_that_cannot_pay_unchanged'] = {f'w{w}': all(
            r[f'w{w}'][0] == r[f'w{w}'][1] for v in per_image.values() for r in v['layers'] if r['name'] in cannot[w])
            for w in WIDTHS}
        res['networks'][label] = rec

    nets = res['networks']
    h1 = {label: {f'w{w}': all(nets[label]['per_image'][k][f'w{w}'][0] == nets[label]['per_image'][k][f'w{w}'][1]
                               for k in nets[label]['per_image'])
                  for w in WIDTHS if not nets[label]['can_pay'][f'w{w}']} for label in labels}
    pooled = lambda label, w: nets[label]['summary'][f'w{w}']['headline_79']['pooled_pct']
    h3_nets = [label for label in labels if nets[label]['can_pay']['w2']]
    res['verdicts'] = dict(
        H1=dict(claim='permuted count == original count on every image (80) wherever bounds.json says zero',
                checked=h1, holds=all(all(v.values()) for v in h1.values())),
        H2=dict(claim='W=4 pooled saving over the 79 images > 0 for every network',
                pooled_pct={label: pooled(label, 4) for label in labels},
                holds=all(pooled(label, 4) > 0 for label in labels)),
        H3=dict(claim='W=2 pooled saving over the 79 images > 0 wherever bounds.json says can pay',
                pooled_pct={label: pooled(label, 2) for label in h3_nets},
                holds=all(pooled(label, 2) > 0 for label in h3_nets)))
    if args.networks:
        res['partial'] = f'only {labels}: the verdicts cover these networks alone'
    res['wall_seconds'] = round(time.time() - t0)
    write_json(args.out, res)

    print(f'\n{"network":<26}{"W":>2} {"min":>7} {"median":>7} {"max":>7} {"pooled":>7} {"<=0":>4} {"worse":>6}'
          f' {"05.png":>7} {"01.png":>7}')
    for label in labels:
        for w in WIDTHS:
            s = nets[label]['summary'][f'w{w}']
            h = s['headline_79']
            print(f'{label:<26}{w:>2} {h["min_pct"]:7.3f} {h["median_pct"]:7.3f} {h["max_pct"]:7.3f} '
                  f'{h["pooled_pct"]:7.3f} {h["images_saving_le_0"]:>4} {h["image_layers_worse"]:>6} '
                  f'{s["05.png"]["saving_pct"]:7.3f} {s["01.png"]["saving_pct"]:7.3f}')
    for k, v in res['verdicts'].items():
        print(k, 'holds' if v['holds'] else 'FAILS', '-', v['claim'])
    print('wrote', args.out)


if __name__ == '__main__':
    main()
