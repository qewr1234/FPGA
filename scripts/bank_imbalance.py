"""Measure what the static `t mod T` bank assignment costs on the real data.

A banked core sends tap t to bank t mod T. The banks run in lockstep, so a window
takes as long as its fullest bank: T * max(count) instead of the sum of counts.
This reports that ratio for the evaluation probe.

The ratio is NOT an unaccounted overhead -- the measured cycle counts already
contain it, because the board ran this same data. It is here to say how skewed
this layer is, so the limitation can be stated with a number instead of a guess.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from legacy_run_checks import read_probe  # noqa: E402


def imbalance(windows, T):
    served = 0
    work = 0
    worst = 0.0
    for row in windows:
        counts = [0]*T
        for t, v in enumerate(row):
            if v:
                counts[t % T] += 1
        nz = sum(counts)
        if nz == 0:
            continue
        work += nz
        served += max(counts)*T
        worst = max(worst, max(counts)*T/nz)
    return served/work, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='evaluation', choices=['evaluation', 'calibration'])
    ap.add_argument('--banks', type=int, nargs='+', default=[2, 4, 8, 16])
    args = ap.parse_args()

    x, _w, _b, _ids, _y = read_probe(ROOT/'data'/(args.split+'.wpr'))
    N, K = len(x), len(x[0])
    rate = [sum(1 for row in x if row[t])/N for t in range(K)]
    print(f'{args.split}: {N} windows, K={K}')
    print(f'nonzero rate per tap: mean {sum(rate)/K:.4f}, min {min(rate):.4f}, max {max(rate):.4f}')
    print()
    print('  T   mean imbalance   worst window')
    for T in args.banks:
        mean, worst = imbalance(x, T)
        print(f'{T:3d}   {mean:13.4f}x  {worst:12.4f}x')


if __name__ == '__main__':
    main()
