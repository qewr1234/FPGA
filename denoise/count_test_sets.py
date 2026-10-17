"""Core cycles of the integer networks on every test image, for each input structure.

    python denoise/count_test_sets.py [--jobs 4]   # writes denoise/test_set_counts.json

The board ran one image (Set12 05.png) per network. In sparse mode a window's
compute depends on its zero activations, so on a port wider than one value per
cycle the cycles depend on the image and on the trained weights. This script
rebuilds every layer's windows for all 80 test images (Set12, BSD68; the noise
of int_eval, seed 0) with the board driver's host emulation, for each network
and seed, and counts them with the per-window rule of wider_ports.py:

    window = max(feed + 1, ceil(COUT/16) * per_group, COUT)

    feed       ceil(K/w) for w values per cycle; C_in for on-chip line buffers
    per_group  max(1, max over banks of the window's nonzero taps) (sparse,
               as on the board); ceil(K/4) (dense bound)

On 05.png this count is within 0.005% of the board at w = 1 and w = 4 for the
four board networks (w4_measured.json; the per-layer remainder is the fill
and drain of w4_gaps.py, left out here). For the other images and networks
it is a count, not a measurement. It also records the multiplications: dense
(K * COUT per window) and nonzero (nonzero taps * COUT, the products the
sparse core actually forms).
"""
import argparse
import concurrent.futures
import contextlib
import io
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from predict_w4 import P, T  # noqa: E402

MODELS = {
    'A': 'dn_d7_c32_es',
    'B + QAT': 'dn_d10_c64_us_es_qat',
    'B-32 ReLU + QAT s1': 'dn_d10_c32_us_fx_qat',
    'B-32 ReLU + QAT s2': 'dn_d10_c32_us_fx_s2_qat',
    'B-32 ReLU + QAT s3': 'dn_d10_c32_us_fx_s3_qat',
    'B-32 maxout + QAT s1': 'dn_d10_c32_us_mo_fx_qat',
    'B-32 maxout + QAT s2': 'dn_d10_c32_us_mo_fx_s2_qat',
    'B-32 maxout + QAT s3': 'dn_d10_c32_us_mo_fx_s3_qat',
    'B-32 averaging + QAT s2': 'dn_d10_c32_us_avg_fx_s2_qat',
    '10 x 45 ReLU + QAT': 'dn_d10_c45_us_fx_qat',
}
SETS = ['Set12', 'BSD68']
STRUCTS = ['w1', 'w2', 'w4', 'line_buffer']


def feed(struct, L):
    if struct == 'line_buffer':
        cin, r = divmod(L['K'], L['kh']*L['kw'])
        assert r == 0, (L['name'], L['K'])
        return cin
    return math.ceil(L['K']/int(struct[1:]))


def layer_counts(L, x):
    """Summed cycles per structure and mode, and multiplications, of one layer's windows."""
    k, cout = L['K'], L['COUT']
    groups = math.ceil(cout/P)
    nz = x != 0
    bank_max = np.stack([nz[:, b::T].sum(1) for b in range(T)], 1).max(1)
    issue = {'sparse': groups*np.maximum(bank_max, 1), 'dense': np.full(x.shape[0], groups*math.ceil(k/T))}
    out = {}
    for s in STRUCTS:
        f = feed(s, L) + 1
        for mode, iss in issue.items():
            out[f'{mode}_{s}'] = int(np.maximum(np.maximum(f, iss), cout).sum())
    out['dense_mults'] = int(x.shape[0])*k*cout
    out['nonzero_mults'] = int(nz.sum())*cout
    return out


def count(label, set_name):
    model = MODELS[label]
    man, layers = run_denoise.load_layers(HERE/'export'/model)
    per_image = {}
    real = run_denoise.run_layer
    for name, clean, noisy in test_noise(load_set(set_name), man['sigma'], seed=0):
        rows = []

        def capture(L, x, args, tag):
            rows.append(dict(name=L['name'], K=L['K'], COUT=L['COUT'], windows=int(x.shape[0]), **layer_counts(L, x)))
            return real(L, x, args, tag)

        run_denoise.run_layer = capture
        try:
            q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
            with contextlib.redirect_stdout(io.StringIO()):
                run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'count')
        finally:
            run_denoise.run_layer = real
        tot = {k: sum(r[k] for r in rows) for k in rows[0] if k not in ('name', 'K', 'COUT', 'windows')}
        per_image[name] = dict(pixels=int(clean.shape[0]*clean.shape[1]), **tot)
    return label, set_name, per_image


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--out', type=Path, default=HERE/'test_set_counts.json')
    args = ap.parse_args()
    res = {label: dict(model=m, sets={}) for label, m in MODELS.items()}
    jobs = [(label, s) for s in reversed(SETS) for label in MODELS]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(count, *j) for j in jobs]):
            label, set_name, per_image = fut.result()
            px = sum(r['pixels'] for r in per_image.values())
            summary = {k: sum(r[k] for r in per_image.values())/px for k in next(iter(per_image.values())) if k != 'pixels'}
            res[label]['sets'][set_name] = dict(pixels=px, per_pixel=summary, per_image=per_image)
            print(f'{label:<24}{set_name:<6} w1 {summary["sparse_w1"]:7.1f}  w4 {summary["sparse_w4"]:7.1f}'
                  f'  (dense {summary["dense_w4"]:7.1f})', flush=True)
    out = dict(what='per-window count on every test image (not a board measurement except where w4_measured.json '
                    'and board_runs/ say so)',
               rule='window = max(feed + 1, ceil(COUT/16) * per_group, COUT); fill and drain left out',
               noise='Set12 and BSD68, sigma 25, test_noise seed 0 (as int_eval)', networks=res)
    args.out.write_text(json.dumps(out, indent=1)+'\n')
    print('wrote', args.out)


if __name__ == '__main__':
    main()
