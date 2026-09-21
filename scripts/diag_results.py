"""Say how build/board/results.bin differs from gold.bin, beyond "it differs".

A wrong sum and a correctly-computed stream that landed at the wrong offset look
the same in a mismatch count, and ReLU puts zeros in well over half the outputs,
so two unrelated streams already agree about 40% of the time. This scans for the
shift that best explains what came back, and reports whether the values are the
right ones in the wrong place.

  python scripts/diag_results.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT/'build'/'board'
COUT = 128


def load(name):
    p = BOARD/name
    if not p.exists():
        raise SystemExit(f'{p} is missing')
    return np.fromfile(p, dtype='<i4')


def scan(got, gold, lags):
    """Mismatch count for each candidate lag, comparing only the overlap."""
    out = {}
    for lag in lags:
        a, b = (got[lag:], gold[:got.size-lag]) if lag >= 0 else \
               (got[:got.size+lag], gold[-lag:])
        n = min(a.size, b.size)
        if n == 0:
            continue
        out[lag] = (int((a[:n] != b[:n]).sum()), n)
    return out


def main():
    got, gold = load('results.bin'), load('gold.bin')
    print(f'results.bin {got.size} words, gold.bin {gold.size} words')
    if got.size != gold.size:
        print('  sizes differ -- that alone explains a mismatch count')

    bad = int((got != gold).sum())
    print(f'aligned            : {bad} / {gold.size} mismatched '
          f'({bad/gold.size:.4f})')
    print(f'zeros in gold      : {(gold == 0).mean():.4f} '
          f'-- unrelated streams agree about this often')
    print(f'zeros in results   : {(got == 0).mean():.4f}')

    # Whole windows first, then single words, then anything in between.
    lags = sorted(set([w*COUT for w in range(-8, 9)] + list(range(-8, 9))))
    res = scan(got, gold, lags)
    best = min(res, key=lambda k: res[k][0]/res[k][1])
    print('\nbest shifts (lag in words; +n means results lag gold by n):')
    for lag, (b, n) in sorted(res.items(), key=lambda kv: kv[1][0]/kv[1][1])[:5]:
        w = lag/COUT
        tag = f'{w:+.0f} window(s)' if lag % COUT == 0 else f'{lag:+d} word(s)'
        print(f'  {tag:16s} {b:7d} / {n} mismatched ({b/n:.4f})')

    b, n = res[best]
    if best != 0 and b/n < 0.01:
        print(f'\n-> the values are right and the stream is offset by {best} words '
              f'({best/COUT:+.0f} window(s)). The core computes correctly; '
              f'the results land in the wrong place.')
    elif best == 0 and b == 0:
        print('\n-> results.bin matches gold.bin exactly.')
    else:
        print('\n-> no shift explains it, so the values themselves are wrong.')
        i = int(np.argmax(got != gold))
        print(f'   first mismatch at word {i} '
              f'(window {i//COUT}, channel {i%COUT}): '
              f'got {got[i]}, want {gold[i]}')
        w0 = got[:COUT]
        print(f'   window 0 of results: {int((w0 == 0).sum())} zeros, '
              f'min {w0.min()}, max {w0.max()}')
        print(f'   window 0 of gold   : {int((gold[:COUT] == 0).sum())} zeros, '
              f'min {gold[:COUT].min()}, max {gold[:COUT].max()}')


if __name__ == '__main__':
    main()
