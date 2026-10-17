"""Core cycles of the board networks on a 4-values-per-cycle window port, predicted
before that bitstream runs.

    python denoise/predict_w4.py            # writes denoise/w4_prediction.json

For each of the four board networks it rebuilds Set12 05.png's layer inputs with
the board driver's host emulation (scripts/run_denoise.py), the windows the core
will actually see, and counts per window what the banked core spends (P = 16
lanes, T = 4 banks, tap t in bank t % 4):

    load   = K'/W + 1       K' = K padded up to a multiple of W (zero taps); the
                            +1 is the start handshake between windows
    issue  = ceil(COUT/16) * max(1, max over banks of the bank's nonzero taps)
                            (sparse mode, which every board run uses; dense mode
                            would be ceil(K'/4) per group)
    window = max(load, issue, COUT)     COUT: outputs leave one per cycle

summed over the windows of every layer. W = 1 is the bitstream already measured,
so the same count is checked against its recorded per-layer cycles first
(denoise/board_runs/<model>_05.json): it must agree to within the few hundred
cycles of pipeline fill and drain per run, or the W = 4 numbers mean nothing.
W = 4 is the prediction. Nothing here depends on a W = 4 measurement.
"""
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

P, T = 16, 4
MODELS = {'A': 'dn_d7_c32_es', 'B + QAT': 'dn_d10_c64_us_es_qat',
          'B-32 maxout + QAT': 'dn_d10_c32_us_mo_fx_qat', 'B-32 ReLU + QAT': 'dn_d10_c32_us_fx_qat'}
IMAGE = '05.png'


def layer_windows(model):
    """[(layer record, windows (N, K) uint8)] of IMAGE, as the driver builds them."""
    export = HERE/'export'/model
    man, layers = run_denoise.load_layers(export)
    got = []
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        got.append((L, x.copy()))
        return real(L, x, args, tag)

    run_denoise.run_layer = capture
    try:
        name, clean, noisy = next(t for t in test_noise(load_set('Set12'), man['sigma'], seed=0) if t[0] == IMAGE)
        q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
        with contextlib.redirect_stdout(io.StringIO()):
            run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'predict')
    finally:
        run_denoise.run_layer = real
    return got, clean.shape


def window_cycles(x, k, cout, w, sparse=True):
    """Per-window cycles of one layer on a W-wide port (see the module docstring)."""
    kp = math.ceil(k/w)*w
    if kp > k:
        x = np.pad(x, ((0, 0), (0, kp-k)))
    groups = math.ceil(cout/P)
    if sparse:
        per_bank = np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1)
        per_group = np.maximum(per_bank.max(1), 1)
    else:
        per_group = np.full(x.shape[0], math.ceil(kp/T))
    return np.maximum(np.maximum(kp//w + 1, groups*per_group), cout)


def main():
    out = dict(image=IMAGE, P=P, T=T, mode='sparse (mode_seq 1), as every board run',
               formula='window = max(ceil(K/W)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT)', networks={})
    for label, model in MODELS.items():
        got, (h, w_img) = layer_windows(model)
        pixels = h*w_img
        board = json.loads((HERE/'board_runs'/f'{model}_05.json').read_text())['images'][0]['layers']
        rec = dict(model=model, layers=[])
        tot = {1: 0, 4: 0, '4dense': 0}
        for (L, x), b in zip(got, board):
            assert b['name'] == L['name'] and b['windows'] == x.shape[0]
            c1 = int(window_cycles(x, L['K'], L['COUT'], 1).sum())
            c4 = int(window_cycles(x, L['K'], L['COUT'], 4).sum())
            c4d = int(window_cycles(x, L['K'], L['COUT'], 4, sparse=False).sum())
            rec['layers'].append(dict(name=L['name'], K=L['K'], COUT=L['COUT'], windows=int(x.shape[0]),
                                      board_w1=b['cycles'], predicted_w1=c1, w1_gap=b['cycles']-c1,
                                      predicted_w4=c4, predicted_w4_dense=c4d))
            tot[1] += c1; tot[4] += c4; tot['4dense'] += c4d
        rec['board_w1_total'] = sum(b['cycles'] for b in board)
        rec['predicted_w1_total'] = tot[1]
        rec['predicted_w4_total'] = tot[4]
        rec['predicted_w4_dense_total'] = tot['4dense']
        rec['pixels'] = pixels
        rec['per_pixel'] = dict(board_w1=rec['board_w1_total']/pixels, predicted_w4=tot[4]/pixels,
                                predicted_w4_dense=tot['4dense']/pixels)
        out['networks'][label] = rec
        gaps = [l['w1_gap'] for l in rec['layers']]
        print(f'{label:<18} W=1 board {rec["board_w1_total"]:>11,}  counted {tot[1]:>11,}  '
              f'(per-layer gaps {min(gaps)}..{max(gaps)})   W=4 predicted {tot[4]:>11,} '
              f'= {tot[4]/pixels:7.1f}/px (dense {tot["4dense"]/pixels:7.1f})')
    n = out['networks']
    r = lambda a, b, k: n[a]['per_pixel'][k]/n[b]['per_pixel'][k]
    out['ratios'] = {'B/A at W=1 (board)': r('B + QAT', 'A', 'board_w1'),
                     'B/A at W=4 (predicted)': r('B + QAT', 'A', 'predicted_w4'),
                     'maxout/ReLU at W=1 (board)': r('B-32 maxout + QAT', 'B-32 ReLU + QAT', 'board_w1'),
                     'maxout/ReLU at W=4 (predicted)': r('B-32 maxout + QAT', 'B-32 ReLU + QAT', 'predicted_w4'),
                     'A W=1 / W=4 (predicted speed-up)': n['A']['per_pixel']['board_w1']/n['A']['per_pixel']['predicted_w4']}
    for k, v in out['ratios'].items():
        print(f'{k:<36} {v:.3f}')
    (HERE/'w4_prediction.json').write_text(json.dumps(out, indent=2) + '\n')
    print('wrote', HERE/'w4_prediction.json')


if __name__ == '__main__':
    main()
