"""How much banks decoupled by buffers could save, against the lockstep layouts (a count, not a measurement).

    python bankperm/decouple_bound.py                # writes bankperm/decouple_bound.json
    python bankperm/decouple_bound.py --jobs 3 --sim # also the window-level simulation (slower)

The question a reviewer asks of the lockstep core: instead of a tap layout, why not
give each bank its own window queue (FIFOs), so that a bank with few nonzeros runs
ahead and the imbalance averages out over windows? In rtl/banked_window_mac.sv the
banks cannot: one issue counter (issue_pos) runs to the fullest bank's count and one
adder tree per output lane sums the T banks' products into one accumulator, so a
window costs (1) of PAPER_EN.md, max(load, G * max(1, m), COUT) with G = ceil(COUT/P)
and m the fullest bank's nonzero count.

For B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat, the board network) at W = 4 on the 80
test images (sigma 25, test_noise seed 0, host emulation), every layer's windows are
captured and, per layer of N windows with n_wb the nonzero taps of window w in bank b
(slot j in bank j % 4), under L0 and under the skew L2 (skew_count.skew_order, inputs
of conv2 to conv(L-1)):

  count      sum_w max(load, G * max(1, m_w), COUT)             the lockstep core, (1)
  perfect    sum_w max(load, G * max(1, ceil(n_w / T)), COUT)   perfect balance per window
  fixed_map  max(N * max(load, COUT), G * max_b sum_w n_wb)     any decoupling with the same
                                                                 slot-to-bank map: bank b must
                                                                 issue each of its nonzero taps
                                                                 once per output group, and the
                                                                 window port and the output port
                                                                 still take load and COUT cycles
                                                                 per window (load includes the core's
                                                                 one-cycle start handshake; without it
                                                                 the L0 bound is 6.84%)
  any_map    max(N * max(load, COUT), G * ceil(sum_w n_w / T))  any decoupling and any map

fixed_map and any_map are lower bounds on a layer's cycles for unbounded buffers (they
also let an all-zero window cost nothing, and leave out the fill and drain), so the
savings they give are upper bounds. With --sim, a window-level event simulation of
both cores with D window buffers per bank (D = 2, the core's; 3; unbounded) gives
savings that such designs could reach: in the decoupled one a window's load waits
until every bank has finished window w - D, its COUT outputs (one per cycle) until
every bank has finished it, and a bank with n taps spends G * n cycles. Savings are
pooled (on cycles summed over images) over the 79 images other than the calibration
image Set12 01.png, against L0's count. Nothing here was run on the board or in RTL.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts'), str(ROOT/'bankperm')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from predict_w4 import P, T  # noqa: E402
from skew_count import skew_order  # noqa: E402

MODEL = 'dn_d10_c32_us_fx_qat'
W = 4
CALIBRATION = 'Set12/01.png'
DEPTHS = (2, 3, None)          # window buffers per bank; None: unbounded
BOUNDS = ('count', 'perfect', 'fixed_map', 'any_map')


def simulate(nb, load, g, cout, depth, lockstep):
    """Cycles of one layer: windows load in order on one port, outputs leave in order on one port."""
    n = nb.shape[0]
    work = (g*np.maximum(nb.max(1), 1)).tolist() if lockstep else (g*nb).tolist()
    done = [[0]*T for _ in range(n)]           # per window, the cycle each bank finishes it
    port = out = 0
    for w in range(n):
        free = max(done[w - depth]) if depth is not None and w >= depth else 0
        loaded = max(port, free) + load
        port = loaded
        prev = done[w - 1] if w else [0]*T
        if lockstep:
            done[w] = [max(max(prev), loaded) + work[w]]*T
        else:
            done[w] = [max(prev[b], loaded) + work[w][b] for b in range(T)]
        out = max(out, max(done[w])) + cout
    return out


def layer(L, x, sim):
    k, cout = L['K'], L['COUT']
    g, load = math.ceil(cout/P), math.ceil(k/W) + 1
    nb = np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1).astype(np.int64)
    n, windows = nb.sum(1), x.shape[0]
    r = dict(name=L['name'],
             count=int(np.maximum(np.maximum(load, g*np.maximum(nb.max(1), 1)), cout).sum()),
             perfect=int(np.maximum(np.maximum(load, g*np.maximum(-(-n//T), 1)), cout).sum()),
             fixed_map=int(max(windows*max(load, cout), g*int(nb.sum(0).max()))),
             any_map=int(max(windows*max(load, cout), g*math.ceil(int(n.sum())/T))),
             bank_totals=[int(v) for v in nb.sum(0)])
    if sim:
        for d in DEPTHS:
            r[f'lockstep_D{d or "inf"}'] = simulate(nb, load, g, cout, d, True)
            r[f'decoupled_D{d or "inf"}'] = simulate(nb, load, g, cout, d, False)
    return r


def one_image(job):
    set_name, image, sim = job
    man, layers = run_denoise.load_layers(ROOT/'denoise'/'export'/MODEL)
    real = run_denoise.run_layer
    for name, _, noisy in test_noise(load_set(set_name), man['sigma'], seed=0):
        if name != image:
            continue
        rec = {'L0': [], 'L2': []}

        def capture(L, x, args, tag):
            i = len(rec['L0'])
            c = L['K'] // (L['kh']*L['kw'])
            skewed = 0 < i < len(layers) - 1 and len(L['inputs']) == 1 and c % 4 == 0
            rec['L0'].append(layer(L, x, sim))
            rec['L2'].append(layer(L, x[:, skew_order(L['K'], c)] if skewed else x, sim))
            return real(L, x, args, tag)

        run_denoise.run_layer = capture
        try:
            q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
            with contextlib.redirect_stdout(io.StringIO()):
                run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'dec')
        finally:
            run_denoise.run_layer = real
        return f'{set_name}/{name}', rec
    raise SystemExit(f'{set_name}/{image} not found')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--sim', action='store_true', help='also run the window-level simulation')
    ap.add_argument('--out', default=str(Path(__file__).with_name('decouple_bound.json')))
    args = ap.parse_args()
    jobs = [(s, f, args.sim) for s in ('Set12', 'BSD68') for f, _ in load_set(s)]
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as ex:
        images = dict(ex.map(one_image, jobs))
    fields = BOUNDS + tuple(f'{c}_D{d or "inf"}' for d in DEPTHS for c in ('lockstep', 'decoupled')
                            if args.sim)
    test = [k for k in images if k != CALIBRATION]

    def total(layout, field, keys=test):
        return sum(r[field] for k in keys for r in images[k][layout])

    base = total('L0', 'count')
    pooled = {lay: {f: round(100*(base - total(lay, f))/base, 4) for f in fields} for lay in ('L0', 'L2')}
    # busiest bank's share of the layer's nonzeros, against the mean bank's (1.0: balanced over the layer)
    skew_of_load = {}
    for lay in ('L0', 'L2'):
        per = {}
        for i, r in enumerate(images[test[0]][lay]):
            tot = np.sum([images[k][lay][i]['bank_totals'] for k in test], 0)
            per[r['name']] = round(float(tot.max()/tot.mean()), 4) if tot.sum() else None
        skew_of_load[lay] = per
    out = dict(
        about=__doc__.strip().splitlines()[0],
        model=MODEL, w=W, p=P, t=T, images=len(images), pooled_over=len(test), excluded=CALIBRATION,
        saving_pct_against_L0_count=pooled,
        busiest_bank_over_mean_bank_per_layer=skew_of_load,
        reading=('fixed_map and any_map are upper bounds on the saving of any decoupled design (unbounded '
                 'buffers, all-zero windows free, no fill and drain); the simulated fields are savings such '
                 'designs could reach. All are counts in host emulation.'),
        per_image=images,
    )
    Path(args.out).write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(pooled, indent=1))
    print(json.dumps(skew_of_load, indent=1))


if __name__ == '__main__':
    main()
