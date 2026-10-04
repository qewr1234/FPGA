"""The methods the denoiser is compared with, in exactly its setting.

    python denoise/baselines.py              # Set12 and BSD68, sigma 25
    python denoise/baselines.py --no-bm3d    # skip BM3D (the slow one)

Every method gets the same noisy images (common.test_noise, seed 0): AWGN of
sigma 25, clipped to [0, 1], quantized to 7 bits. Paper numbers are not used,
because the paper's noise is neither clipped nor quantized.

  noisy     the input itself
  gaussian  Gaussian blur; its width is chosen on 40 TRAINING images, never on
            the test sets
  median    3x3 or 5x5 median, whichever is better on the same 40 training images
  bm3d      BM3D (pip package bm3d), told the true sigma -- the usual "oracle
            noise level" protocol. The strongest classical method.

Writes denoise/baselines.json.
"""
import argparse
import json
import time

import numpy as np
from scipy.ndimage import gaussian_filter, median_filter

from common import HERE, add_noise, load_set, psnr, test_noise


def pick(images, make, candidates):
    """The candidate with the best mean PSNR on images."""
    rng = np.random.default_rng(123)
    noisy = [(c, add_noise(c, ARGS.sigma, rng)) for _, c in images]
    score = {c: np.mean([psnr(cl, make(c)(n)) for cl, n in noisy]) for c in candidates}
    best = max(score, key=score.get)
    return best, score


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument('--sigma', type=float, default=25)
    ap.add_argument('--no-bm3d', action='store_true')
    ARGS = args = ap.parse_args()

    tune = load_set('Train400')[::10]                 # 40 training images
    g_sigma, g_scores = pick(tune, lambda s: (lambda x: gaussian_filter(x, s)),
                             [0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0])
    m_size, m_scores = pick(tune, lambda k: (lambda x: median_filter(x, k)), [3, 5])
    print(f'tuned on 40 training images: gaussian sigma={g_sigma}  median {m_size}x{m_size}')

    methods = {
        'noisy':    lambda x: x,
        'gaussian': lambda x: gaussian_filter(x, g_sigma),
        'median':   lambda x: median_filter(x, m_size),
    }
    if not args.no_bm3d:
        import bm3d
        methods['bm3d'] = lambda x: bm3d.bm3d(x, sigma_psd=args.sigma/255.0)

    out = dict(sigma=args.sigma, setting='AWGN, clipped to [0,1], quantized to 7 bits, seed 0',
               gaussian_sigma=g_sigma, median_size=m_size, sets={})
    for set_name in ('Set12', 'BSD68'):
        tests = test_noise(load_set(set_name), args.sigma, seed=0)
        res = {}
        for m, f in methods.items():
            t0 = time.time()
            per = {n: psnr(c, f(noisy)) for n, c, noisy in tests}
            res[m] = dict(mean=float(np.mean(list(per.values()))), per_image=per,
                          seconds=round(time.time()-t0, 1))
            print(f'{set_name:<6} {m:<9} {res[m]["mean"]:6.2f} dB   ({time.time()-t0:.0f} s)', flush=True)
        out['sets'][set_name] = res
    (HERE/'baselines.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(f'wrote {HERE/"baselines.json"}')


if __name__ == '__main__':
    main()
