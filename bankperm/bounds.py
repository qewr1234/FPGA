"""Where a channel-to-bank permutation can change the core's cycles at all.

    python bankperm/bounds.py            # writes bankperm/bounds.json

On the banked core (P = 16 lanes, T = 4 banks, tap t in bank t % 4, sparse
mode) one window of a layer takes

    max(ceil(K/W) + 1, ceil(COUT/P) * max(1, m), COUT)

cycles, m the largest number of nonzero taps in one bank. A permutation of the
layer's input channels changes only m, and m is at most the number of taps a
bank holds, ceil(K/T). So if

    ceil(COUT/P) * ceil(K/T)  <=  max(ceil(K/W) + 1, COUT)

no window of that layer can be bound by its compute, whatever the data, and no
permutation can change its count. This file lists, from the layer shapes alone
(no activations), which layers of each network can pay at W = 1, 2 and 4: the
layers whose input channels the protocol permutes (the inputs of conv2 to
conv(L-1); see PROTOCOL.md) and, for the record, the last layer.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from count_test_sets import MODELS  # noqa: E402

P, T = 16, 4
WIDTHS = (1, 2, 4)


def main():
    out = dict(rule='can pay at W iff ceil(COUT/16)*ceil(K/4) > max(ceil(K/W)+1, COUT)', networks={})
    for label, model in MODELS.items():
        man, layers = run_denoise.load_layers(ROOT/'denoise'/'export'/model)
        rows = []
        for i, L in enumerate(layers):
            if i == 0:
                continue                          # input is the image: never permuted
            k, cout = L['K'], L['COUT']
            top = math.ceil(cout/P)*math.ceil(k/T)
            row = dict(name=L['name'], K=k, COUT=cout, inputs=L['inputs'],
                       permuted=(i < len(layers)-1), max_compute=top)
            for w in WIDTHS:
                floor = max(math.ceil(k/w)+1, cout)
                row[f'floor_w{w}'] = floor
                row[f'can_pay_w{w}'] = top > floor
            rows.append(row)
        net = {f'w{w}': any(r[f'can_pay_w{w}'] for r in rows if r['permuted']) for w in WIDTHS}
        out['networks'][label] = dict(model=model, can_pay=net, layers=rows)
        print(f'{label:<26}' + '  '.join(f'W={w}: {"can pay" if net[f"w{w}"] else "zero":<7}' for w in WIDTHS)
              + f'   (last layer can pay: {any(r[f"can_pay_w{w}"] for r in rows if not r["permuted"] for w in WIDTHS)})')
    (HERE/'bounds.json').write_text(json.dumps(out, indent=1)+'\n')
    print('wrote', HERE/'bounds.json')


if __name__ == '__main__':
    main()
