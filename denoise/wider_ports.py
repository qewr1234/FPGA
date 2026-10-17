"""Core cycles of the four board networks for wider input structures, counted on
real windows instead of estimated from densities.

    python denoise/wider_ports.py            # writes denoise/wider_ports.json

The windows are those of Set12 05.png, rebuilt with the board driver's host
emulation (predict_w4.layer_windows). Per window, with the core's P = 16 lanes
and T = 4 banks (tap t in bank t % 4):

    feed   = values the input structure must bring in for this window, + 1 for
             the start handshake:
               w values per cycle   ceil(K/w)
               line buffer          C_in = K/(kh*kw), one new input pixel
    issue  = ceil(COUT/16) * per_group
               sparse (every board run)  max(1, max over banks of nonzero taps)
               dense bound               ceil(K/4)
    window = max(feed + 1, issue, COUT)

This is the count predict_w4.py made its W=4 prediction with; at w = 1 it is
the board-calibrated model, and sim_w4_layers.py checks it against the RTL at
w = 1 and w = 4 on sampled windows of every layer. Layer fill and drain (tens
to a few hundred cycles per layer) are left out. w = 2 and the line buffer are
hypothetical structures: only the formula, not the hardware, exists for them.

It replaces the sparse estimate of PAPER_KO.md Table III (measured densities
with an assumed bank imbalance of 1.0-1.3, which also did not cap the per-group
cost at ceil(K/4)).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from predict_w4 import MODELS, P, T, layer_windows  # noqa: E402

STRUCTS = ['w1', 'w2', 'w4', 'line_buffer']


def per_window(x, k, cout, feed, sparse):
    groups = math.ceil(cout/P)
    if sparse:
        per_bank = np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1)
        per_group = np.maximum(per_bank.max(1), 1)
    else:
        per_group = np.full(x.shape[0], math.ceil(k/T))
    return np.maximum(np.maximum(feed + 1, groups*per_group), cout)


def feed_of(struct, L):
    k = L['K']
    if struct == 'line_buffer':
        cin, r = divmod(k, L['kh']*L['kw'])
        assert r == 0, (L['name'], k)
        return cin
    return math.ceil(k/int(struct[1:]))


def main():
    out = dict(image='05.png', P=P, T=T, formula='window = max(feed + 1, ceil(COUT/16)*per_group, COUT)',
               structures={'w1': 'one value per cycle (the board build)', 'w2': 'two values per cycle',
                           'w4': 'four values per cycle (the W=4 build)',
                           'line_buffer': 'on-chip line buffers: C_in new values per window'},
               networks={})
    for label, model in MODELS.items():
        got, (h, w) = layer_windows(model)
        px = h*w
        rec = dict(model=model, pixels=px, per_pixel={}, layers=[])
        for mode in ('sparse', 'dense'):
            for s in STRUCTS:
                tot = 0
                for L, x in got:
                    c = int(per_window(x, L['K'], L['COUT'], feed_of(s, L), mode == 'sparse').sum())
                    tot += c
                    if mode == 'sparse':
                        if len(rec['layers']) < len(got):
                            rec['layers'].append(dict(name=L['name'], K=L['K'], COUT=L['COUT'],
                                                      windows=int(x.shape[0])))
                        rec['layers'][[l['name'] for l in rec['layers']].index(L['name'])][s] = c
                rec['per_pixel'][f'{mode}_{s}'] = tot/px
        out['networks'][label] = rec
        pp = rec['per_pixel']
        print(f'{label:<18}' + ''.join(f'{s:>12} {pp["sparse_"+s]:7.1f} ({pp["dense_"+s]:6.1f})' for s in STRUCTS))
    n = out['networks']
    out['ratios'] = {}
    for mode in ('sparse', 'dense'):
        for s in STRUCTS:
            k = f'{mode}_{s}'
            out['ratios'][k] = {
                'B/A': n['B + QAT']['per_pixel'][k]/n['A']['per_pixel'][k],
                'maxout/ReLU': n['B-32 maxout + QAT']['per_pixel'][k]/n['B-32 ReLU + QAT']['per_pixel'][k]}
            print(f'{k:<18} B/A {out["ratios"][k]["B/A"]:.3f}   maxout/ReLU {out["ratios"][k]["maxout/ReLU"]:.3f}')
    (HERE/'wider_ports.json').write_text(json.dumps(out, indent=2)+'\n')
    print('wrote', HERE/'wider_ports.json')


if __name__ == '__main__':
    main()
