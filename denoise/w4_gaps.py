"""What the per-layer gaps between the board and the per-window count are.

    python denoise/w4_gaps.py            # writes denoise/w4_gaps.json

The count (predict_w4.window_cycles, summed over a layer's windows) leaves out
what a run pays once: filling the pipeline before the first window and draining
it after the last. This script tests one rule for that, on the board runs of the
four networks at W=1 (w4_prediction.json, w1_gap) and W=4 (w4_measured.json):

    gap - IN_STALL = min(load, last) + c

    load   the cycles one window takes to load, ceil(K/w) + 1
    last   the last window's compute, ceil(COUT/16) * max over banks of its
           nonzero taps (sparse mode)
    c      19 on hidden layers; COUT + 3 on the last layers

Every window of a layer loads in the same time, and the next window loads
while the current one computes, so a run takes one load, then max(compute,
load) per window, then the last window's compute. The count, max(load, compute)
per window, therefore leaves out min(load, last) once. At W=1 the load is
always the longer, so the gap is the last window's compute + 19. The first layers are bound by their
COUT outputs and are listed without a rule. The rule was read off the gaps
after the board run; it is a description, not a prediction.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from predict_w4 import MODELS, P, T, layer_windows  # noqa: E402


def load_and_last(x, k, cout, w):
    kp = math.ceil(k/w)*w
    last = np.pad(x[-1], (0, kp-k))
    per_bank = max(int((last[b::T] != 0).sum()) for b in range(T))
    return kp//w + 1, math.ceil(cout/P)*max(per_bank, 1)


def main():
    meas = json.loads((HERE/'w4_measured.json').read_text())['networks']
    pred = json.loads((HERE/'w4_prediction.json').read_text())['networks']
    out = dict(rule='gap - in_stall = min(load, last) + c; c = 19 (hidden), COUT + 3 (last layer)',
               networks={})
    held = total = 0
    for label, model in MODELS.items():
        got, _ = layer_windows(model)
        rows = []
        for i, ((L, x), m, p) in enumerate(zip(got, meas[label]['layers'], pred[label]['layers'])):
            kind = 'first' if i == 0 else 'last' if i == len(got) - 1 else 'hidden'
            row = dict(name=m['name'], K=L['K'], COUT=L['COUT'], kind=kind)
            for w, gap, stall in ((1, p['w1_gap'], 0), (4, m['gap'], m['in_stall'])):
                load, last = load_and_last(x, L['K'], L['COUT'], w)
                rec = dict(gap=gap, in_stall=stall, load=load, last=last, rest=gap - stall - min(load, last))
                if kind != 'first':
                    rec['rule_holds'] = rec['rest'] == (19 if kind == 'hidden' else L['COUT'] + 3)
                    held += rec['rule_holds']; total += 1
                row[f'w{w}'] = rec
            rows.append(row)
            print(f"{label:<18}{m['name']:<7}{kind:<7}" + ''.join(
                f"  w{w}: gap {row[f'w{w}']['gap']:4d} stall {row[f'w{w}']['in_stall']:2d}"
                f" min({row[f'w{w}']['load']},{row[f'w{w}']['last']}) + {row[f'w{w}']['rest']}" for w in (1, 4)))
        out['networks'][label] = dict(model=model, layers=rows)
    out['rule_holds'] = f'{held}/{total}'
    print(f'rule holds on {held}/{total} hidden and last layers (W=1 and W=4)')
    (HERE/'w4_gaps.json').write_text(json.dumps(out, indent=2)+'\n')
    print('wrote', HERE/'w4_gaps.json')


if __name__ == '__main__':
    main()
