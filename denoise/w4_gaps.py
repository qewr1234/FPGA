"""What the per-layer gaps between measured cycles and the per-window count are.

    python denoise/w4_gaps.py            # writes denoise/w4_gaps.json

The count (predict_w4.window_cycles, summed over a run's windows) leaves out
what a run pays once: filling the pipeline before the first window and draining
it after the last. This script tests one rule for that, at W=1 and W=4, on the
board runs of the four networks (whole layers; gaps from w4_prediction.json
w1_gap and w4_measured.json) and on the RTL sample of sim_w4_layers.py (512
windows per layer; gaps from w4_rtl_sim.json, and at W=2 from w2_rtl_sim.json
when it exists):

    gap - IN_STALL = min(load, last) + c

    load   the cycles one window takes to load, ceil(K/w) + 1
    last   the run's last window's compute, ceil(COUT/16) * max over banks of
           its nonzero taps (sparse mode)
    c      19 on hidden layers; COUT + 3 on the last layers

Every window of a layer loads in the same time, and each window's compute
overlaps the next window's load, so a run takes one load, then max(compute,
load) for each window but the last, then the last window's compute. The count,
max(load, compute) for every window, therefore leaves out min(load, last) once.
At W=1 the load is always the longer, so on hidden layers the gap is the last
window's compute + 19. The first layers are listed without a rule (at W=4 they
are bound by their COUT outputs). The constants were read off the W=1 and W=4 gaps
after the W=4 board run; at W=2 (w2_rtl_sim.json, run after) the rule met data
it had not been fitted to.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from predict_w4 import MODELS, P, T, layer_windows  # noqa: E402
from sim_w4_layers import sample  # noqa: E402


def load_and_last(last, k, cout, w):
    kp = math.ceil(k/w)*w
    last = np.pad(last, (0, kp-k))
    per_bank = max(int((last[b::T] != 0).sum()) for b in range(T))
    return kp//w + 1, math.ceil(cout/P)*max(per_bank, 1)


def main():
    meas = json.loads((HERE/'w4_measured.json').read_text())['networks']
    pred = json.loads((HERE/'w4_prediction.json').read_text())['networks']
    rtl = json.loads((HERE/'w4_rtl_sim.json').read_text())
    f2 = HERE/'w2_rtl_sim.json'
    rtl2 = json.loads(f2.read_text()) if f2.exists() else None
    out = dict(rule='gap - in_stall = min(load, last) + c; c = 19 (hidden), COUT + 3 (last layer)',
               networks={})
    held = dict(board=[0, 0], rtl_sample=[0, 0], rtl_sample_w2=[0, 0])
    for label, model in MODELS.items():
        got, _ = layer_windows(model)
        rows = []
        for i, ((L, x), m, p, r) in enumerate(zip(got, meas[label]['layers'], pred[label]['layers'],
                                                  rtl['networks'][label]['layers'])):
            kind = 'first' if i == 0 else 'last' if i == len(got) - 1 else 'hidden'
            row = dict(name=m['name'], K=L['K'], COUT=L['COUT'], kind=kind)
            rtl_last = x[sample(x.shape[0], rtl['windows_per_layer'])[-1]]
            runs = [('board_w1', x[-1], 1, p['w1_gap'], 0), ('board_w4', x[-1], 4, m['gap'], m['in_stall']),
                    ('rtl_w1', rtl_last, 1, r['gap_w1'], 0), ('rtl_w4', rtl_last, 4, r['gap_w4'], 0)]
            if rtl2:
                r2 = rtl2['networks'][label]['layers'][i]
                assert r2['name'] == m['name']
                runs.append(('rtl_w2', x[sample(x.shape[0], rtl2['windows_per_layer'])[-1]], 2, r2['gap_w2'], 0))
            for key, last_window, w, gap, stall in runs:
                load, last = load_and_last(last_window, L['K'], L['COUT'], w)
                rec = dict(gap=gap, in_stall=stall, load=load, last=last, rest=gap - stall - min(load, last))
                if kind != 'first':
                    rec['rule_holds'] = rec['rest'] == (19 if kind == 'hidden' else L['COUT'] + 3)
                    h = held['board' if key.startswith('board') else 'rtl_sample_w2' if key == 'rtl_w2'
                             else 'rtl_sample']
                    h[0] += rec['rule_holds']; h[1] += 1
                row[key] = rec
            rows.append(row)
            print(f"{label:<18}{m['name']:<7}{kind:<7}" + ''.join(
                f"  {k}: {row[k]['gap']:4d}-{row[k]['in_stall']:2d} = min({row[k]['load']},{row[k]['last']})"
                f" + {row[k]['rest']}" for k, *_ in runs))
        out['networks'][label] = dict(model=model, layers=rows)
    out['rule_holds'] = {k: f'{a}/{b}' for k, (a, b) in held.items() if b}
    print("rule holds on the hidden and last layers:",,
          ', '.join(f'{k} {v}' for k, v in out['rule_holds'].items()))
    (HERE/'w4_gaps.json').write_text(json.dumps(out, indent=2)+'\n')
    print('wrote', HERE/'w4_gaps.json')


if __name__ == '__main__':
    main()
