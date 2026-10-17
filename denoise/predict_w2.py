"""Core cycles of the board networks on a 2-values-per-cycle window port, predicted
before that bitstream exists.

    python denoise/predict_w2.py            # writes denoise/w2_prediction.json

Same count as predict_w4.py (window = max(ceil(K/W)+1, ceil(COUT/16) * max(1,
max_b nnz_b), COUT), sparse mode, Set12 05.png as the board driver builds it),
at W = 2: the per-pixel numbers are the ones wider_ports.json already gave for
w2 in commit 55f13b4. What this file adds, written before any W = 2 hardware:

  - per layer, the count at W = 1, 2 and 4, and the W = 1 board cycles where a
    board run exists (the check that the count means anything);
  - per layer, the exact cycles the run should take, count + fill and drain,
    with the rule w4_gaps.py read off the W = 1 and W = 4 runs:
        min(load, last) + 19 on hidden layers, + COUT + 3 on the last layer
    (load = ceil(K/W)+1, last = the last window's compute). The first layers
    (bound by their COUT outputs) get no exact number. That rule was found
    after the W = 4 run; W = 2 is the first run it meets unseen;
  - the parameter-matched 10 x 45 ReLU network (dn_d10_c45_us_fx_qat, never run
    on the board), at W = 1, 2 and 4, so a board run of it at any width is a
    prediction too.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from predict_w4 import IMAGE, P, T, layer_windows, window_cycles  # noqa: E402
from w4_gaps import load_and_last  # noqa: E402

MODELS = {'A': 'dn_d7_c32_es', 'B + QAT': 'dn_d10_c64_us_es_qat',
          'B-32 maxout + QAT': 'dn_d10_c32_us_mo_fx_qat', 'B-32 ReLU + QAT': 'dn_d10_c32_us_fx_qat',
          '10 x 45 ReLU + QAT': 'dn_d10_c45_us_fx_qat'}
WIDTHS = (1, 2, 4)


def main():
    out = dict(image=IMAGE, P=P, T=T, mode='sparse (mode_seq 1), as every board run',
               formula='window = max(ceil(K/W)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT)',
               exact='count + min(load, last) + 19 (hidden layers), + COUT + 3 (last layer); none for the first',
               networks={})
    for label, model in MODELS.items():
        got, (h, w_img) = layer_windows(model)
        pixels = h*w_img
        f = HERE/'board_runs'/f'{model}_05.json'
        board = json.loads(f.read_text())['images'][0]['layers'] if f.exists() else None
        rec = dict(model=model, pixels=pixels, layers=[])
        for i, (L, x) in enumerate(got):
            kind = 'first' if i == 0 else 'last' if i == len(got) - 1 else 'hidden'
            row = dict(name=L['name'], K=L['K'], COUT=L['COUT'], windows=int(x.shape[0]), kind=kind)
            for w in WIDTHS:
                c = int(window_cycles(x, L['K'], L['COUT'], w).sum())
                row[f'predicted_w{w}'] = c
                if kind != 'first':
                    load, last = load_and_last(x[-1], L['K'], L['COUT'], w)
                    row[f'exact_w{w}'] = c + min(load, last) + (19 if kind == 'hidden' else L['COUT'] + 3)
            if board:
                b = board[i]
                assert b['name'] == L['name'] and b['windows'] == x.shape[0]
                row['board_w1'] = b['cycles']
                row['w1_gap'] = b['cycles'] - row['predicted_w1']
            rec['layers'].append(row)
        for w in WIDTHS:
            rec[f'predicted_w{w}_total'] = sum(r[f'predicted_w{w}'] for r in rec['layers'])
        if board:
            rec['board_w1_total'] = sum(r['board_w1'] for r in rec['layers'])
        rec['per_pixel'] = {f'predicted_w{w}': rec[f'predicted_w{w}_total']/pixels for w in WIDTHS}
        if board:
            rec['per_pixel']['board_w1'] = rec['board_w1_total']/pixels
        out['networks'][label] = rec
        print(f'{label:<20}' + ''.join(f'  W={w} {rec["per_pixel"][f"predicted_w{w}"]:7.1f}/px' for w in WIDTHS)
              + (f'   W=1 board {rec["per_pixel"]["board_w1"]:7.1f}/px' if board else '   (no board run)'))
    n = out['networks']
    pp = lambda a, k: n[a]['per_pixel'][k]
    out['ratios'] = {}
    for w in WIDTHS:
        out['ratios'][f'W={w}'] = {
            'B/A': pp('B + QAT', f'predicted_w{w}')/pp('A', f'predicted_w{w}'),
            'maxout/ReLU': pp('B-32 maxout + QAT', f'predicted_w{w}')/pp('B-32 ReLU + QAT', f'predicted_w{w}'),
            '45-channel/maxout': pp('10 x 45 ReLU + QAT', f'predicted_w{w}')/pp('B-32 maxout + QAT', f'predicted_w{w}')}
        print(f'W={w}: ' + '   '.join(f'{k} {v:.3f}' for k, v in out['ratios'][f'W={w}'].items()))
    (HERE/'w2_prediction.json').write_text(json.dumps(out, indent=2) + '\n')
    print('wrote', HERE/'w2_prediction.json')


if __name__ == '__main__':
    main()
