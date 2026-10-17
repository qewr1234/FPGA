"""Do the cycle ratios the paper rests on hold on every test image and seed?

    python denoise/test_set_ratios.py     # reads test_set_counts.json, writes test_set_ratios.json

test_set_counts.json (count_test_sets.py) has, for every Set12 and BSD68 image,
the per-window count of each network at w = 1, 2, 4 and with line buffers. This
takes, per image, the ratios B/A, maxout/ReLU (every pair of the three seeds of
each) and 10x45-ReLU/maxout (every maxout seed), and reports their range over
the 80 images and the seed pairs, in sparse mode (as on the board) and for the
dense bound. It also reports the multipliers' use: nonzero products (what the
sparse core multiplies) and dense products (the paper's "Util.") per 64 x
cycles, over all 80 images.

Counts, not board measurements: on 05.png the count is within 0.005% of the
board at w = 1 and w = 4 for the four board networks.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETS = ('Set12', 'BSD68')
STRUCTS = ('w1', 'w2', 'w4', 'line_buffer')
RELU = [f'B-32 ReLU + QAT s{i}' for i in (1, 2, 3)]
MAXOUT = [f'B-32 maxout + QAT s{i}' for i in (1, 2, 3)]


def main():
    d = json.loads((HERE/'test_set_counts.json').read_text())['networks']

    def per_image(label, key):
        return {(s, n): v[key]/v['pixels'] for s in SETS for n, v in d[label]['sets'][s]['per_image'].items()}

    def total(label, key):
        return sum(v[key] for s in SETS for v in d[label]['sets'][s]['per_image'].values())

    out = dict(images=sum(len(d['A']['sets'][s]['per_image']) for s in SETS), ratios={}, per_pixel={},
               multiplier_use={})
    for mode in ('sparse', 'dense'):
        for st in STRUCTS:
            k = f'{mode}_{st}'
            a, b = per_image('A', k), per_image('B + QAT', k)
            pairs = {'B/A': [b[i]/a[i] for i in a],
                     'maxout/ReLU': [per_image(m, k)[i]/per_image(r, k)[i] for m in MAXOUT for r in RELU for i in a],
                     '45-channel/maxout': [per_image('10 x 45 ReLU + QAT', k)[i]/per_image(m, k)[i]
                                           for m in MAXOUT for i in a]}
            out['ratios'][k] = {n: dict(min=min(v), max=max(v)) for n, v in pairs.items()}
            out['ratios'][k]['maxout/ReLU']['below_1.5'] = sum(x < 1.5 for x in pairs['maxout/ReLU'])
            out['ratios'][k]['maxout/ReLU']['pairs'] = len(pairs['maxout/ReLU'])
            print(f'{k:<20}' + '   '.join(f'{n} {r["min"]:.3f}..{r["max"]:.3f}' for n, r in out['ratios'][k].items()))
    px = sum(d['A']['sets'][s]['pixels'] for s in SETS)
    for label in d:
        out['per_pixel'][label] = {st: total(label, f'sparse_{st}')/px for st in STRUCTS}
        out['multiplier_use'][label] = {
            st: dict(nonzero=total(label, 'nonzero_mults')/(64*total(label, f'sparse_{st}')),
                     dense=total(label, 'dense_mults')/(64*total(label, f'sparse_{st}'))) for st in ('w1', 'w2', 'w4')}
    print('\nmultiplier use, nonzero (dense) products per 64 x cycles:')
    for label, u in out['multiplier_use'].items():
        print(f'  {label:<26}' + ''.join(f'  {st} {v["nonzero"]:.2f} ({v["dense"]:.2f})' for st, v in u.items()))
    (HERE/'test_set_ratios.json').write_text(json.dumps(out, indent=2)+'\n')
    print('wrote', HERE/'test_set_ratios.json')


if __name__ == '__main__':
    main()
