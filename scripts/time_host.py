"""Host-side time per 256x256 image for each exported denoiser: what the PC does between core runs.

    python scripts/time_host.py [model ...]        # default: the five board-run models

For every node but the last it times what scripts/run_denoise.py does on the host:
im2col of the input map (the windows the core streams), requantization of the
core's INT32 accumulators to 7-bit codes, and the post-op (maxout's max of each
pair). Inputs are random codes of the right shapes, so the time does not depend
on the image. The last layer's conversion to pixels is left out (one channel per
phase, negligible). Board transfers (JTAG) and the board-side check are not host
inference work and are not timed; scripts/run_denoise.py reports them separately.
The core time to compare with is the board's measured cycles at 50 MHz.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_cifar import im2col, requant  # noqa: E402

MODELS = ['dn_d7_c32_es', 'dn_d10_c64_us_es', 'dn_d10_c64_us_es_qat', 'dn_d10_c32_us_mo_es', 'dn_d10_c32_us_mo_es_qat']


def best(f, n=5):
    t = 1e9
    for _ in range(n):
        t0 = time.perf_counter(); f(); t = min(t, time.perf_counter() - t0)
    return t


def main():
    names = sys.argv[1:] or MODELS
    rng = np.random.default_rng(0)
    for name in names:
        man = json.loads((ROOT/'denoise'/'export'/name/'manifest.json').read_text())
        side = 128 if man.get('unshuffle') else 256
        tot = dict(im2col=0.0, requant=0.0, post=0.0)
        for L in man['layers'][:-1]:
            kh, kw = L.get('kh', 3), L.get('kw', 3)
            cin = L['K']//(kh*kw)
            q = rng.integers(0, 128, (1, cin, side, side), dtype=np.uint8)
            tot['im2col'] += best(lambda: im2col(q, kh, kw, None, L.get('dilation', 1), L.get('stride', 1)))
            acc = rng.integers(0, 1 << 20, (side*side, L['COUT']), dtype=np.int64)
            fac = np.asarray(L['requant'], dtype=np.float64)
            tot['requant'] += best(lambda: requant(acc, fac))
            if L.get('post', 'maxout' if man.get('maxout') else 'none') == 'maxout':
                r = requant(acc, fac).reshape(side, side, L['COUT']).transpose(2, 0, 1)
                c = L['COUT']//2
                tot['post'] += best(lambda: np.maximum(r[:c], r[c:]))
        host = sum(tot.values())
        run = ROOT/'denoise'/'board_runs'/f'{name}_05.json'
        core = json.loads(run.read_text())['images'][0]['cycles']/50e6 if run.exists() else float('nan')
        print(f'{name:26s} host {host*1e3:6.1f} ms (im2col {tot["im2col"]*1e3:5.1f}, requant {tot["requant"]*1e3:5.1f}, '
              f'post {tot["post"]*1e3:4.1f})   core at 50 MHz {core:5.2f} s   host/core {host/core*100:4.1f}%')


if __name__ == '__main__':
    main()
