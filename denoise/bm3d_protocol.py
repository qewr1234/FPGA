"""How much the paper's input protocol costs BM3D (a reviewer's question).

    python denoise/bm3d_protocol.py sweep   # sigma_psd sweep on the 40 training images baselines.py tunes on
    python denoise/bm3d_protocol.py test    # the three test evaluations on Set12 / BSD68
    python denoise/bm3d_protocol.py all     # both, in order (about 35 minutes on 4 cores)

The networks are trained and tested on noisy images that are clipped to [0, 1]
and quantized to 7 bits (the core's input port). BM3D is given the same input
and the true sigma, which the paper's table reports as "the same input
condition". This script measures what that condition costs BM3D, so the paper
can say how much of its BSD68 margin is protocol: on unclipped float noise
BM3D gains 0.03 dB on Set12 and 0.26 dB on BSD68 (the gain sits on the images
with many saturated pixels); tuning sigma_psd on the training images moves it
by less than 0.1 dB. Results: bm3d_protocol_sweep.json, bm3d_protocol.json.

Three BM3D configurations, all with the SAME noise seed as denoise/baselines.py
(common.test_noise, seed 0):
  1. clip7  : paper's protocol -- noisy = quantize7(clip(x + N(0, 25/255))), sigma_psd = 25/255
  2. raw    : unclipped, unquantized float noisy = x + N(0, 25/255), sigma_psd = 25/255
  3. tuned  : paper's protocol, but sigma_psd picked on the 40 training images
              (Train400[::10], noise rng seed 123 -- exactly what baselines.pick uses)

"""
import os
# one thread per worker; the images are spread over the 4 cores with multiprocessing
for _v in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, median_filter

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from common import add_noise, load_set, psnr, quantize_input, test_noise  # noqa: E402

SIGMA = 25.0
SWEEP = [20, 22, 23, 24, 25, 26, 27, 28, 30]
NPROC = 4


def _bm3d_one(args):
    x, sigma_psd = args
    import bm3d
    return bm3d.bm3d(x, sigma_psd=sigma_psd)


def bm3d_many(pool, images, sigma_psd):
    return pool.map(_bm3d_one, [(x, sigma_psd) for x in images], chunksize=1)


def test_noise_raw(images, sigma, seed=0):
    """Same draws as common.test_noise, but also keeps the unclipped float noisy image.

    Returns [(name, clean, raw_noisy, clip7_noisy)]; clip7 is checked to be
    bit-identical to common.test_noise output.
    """
    rng = np.random.default_rng(seed)
    out = []
    for n, c in images:
        raw = c + rng.standard_normal(c.shape).astype(np.float32)*(sigma/255.0)
        out.append((n, c, raw, quantize_input(raw)))
    ref = test_noise(images, sigma, seed=seed)
    for (n, c, raw, q), (n2, c2, q2) in zip(out, ref):
        assert n == n2 and np.array_equal(q, q2), f'noise mismatch on {n}'
    return out


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def sweep():
    tune = load_set('Train400')[::10]                       # 40 training images, as baselines.py
    rng = np.random.default_rng(123)                        # as baselines.pick
    noisy = [(c, add_noise(c, SIGMA, rng)) for _, c in tune]
    log(f'sweep: {len(noisy)} training images, shapes {sorted(set(c.shape for c, _ in noisy))}')

    # the classical filters' tuning scores, for context (cheap)
    res = dict(n_images=len(noisy), sigma=SIGMA, filters={}, bm3d={})
    for s in [0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0]:
        res['filters'][f'gaussian_{s}'] = float(np.mean([psnr(c, gaussian_filter(n, s)) for c, n in noisy]))
    for k in [3, 5]:
        res['filters'][f'median_{k}'] = float(np.mean([psnr(c, median_filter(n, k)) for c, n in noisy]))
    res['filters']['noisy'] = float(np.mean([psnr(c, n) for c, n in noisy]))
    log('filters on train40: ' + ', '.join(f'{k}={v:.3f}' for k, v in res['filters'].items()))

    with Pool(NPROC) as pool:
        for s in SWEEP:
            t0 = time.time()
            den = bm3d_many(pool, [n for _, n in noisy], s/255.0)
            per = [psnr(c, d) for (c, _), d in zip(noisy, den)]
            res['bm3d'][str(s)] = dict(mean=float(np.mean(per)), per_image=[float(p) for p in per])
            log(f'sweep sigma_psd={s:>2}/255: train40 mean {np.mean(per):.3f} dB  ({time.time()-t0:.0f} s)')
            (HERE/'bm3d_protocol_sweep.json').write_text(json.dumps(res, indent=2))
    best = max(res['bm3d'], key=lambda k: res['bm3d'][k]['mean'])
    res['best_sigma'] = int(best)
    (HERE/'bm3d_protocol_sweep.json').write_text(json.dumps(res, indent=2))
    log(f'sweep best sigma_psd = {best}/255 ({res["bm3d"][best]["mean"]:.3f} dB on train40)')
    return res


def test():
    sw = json.loads((HERE/'bm3d_protocol_sweep.json').read_text())
    best = sw['best_sigma']
    out = dict(sigma=SIGMA, seed=0, best_sigma_from_train40=best, sets={})
    out_path = HERE/'bm3d_protocol.json'
    with Pool(NPROC) as pool:
        for set_name in ('Set12', 'BSD68'):
            data = test_noise_raw(load_set(set_name), SIGMA, seed=0)
            names = [n for n, *_ in data]
            clean = [c for _, c, *_ in data]
            raws = [r for _, _, r, _ in data]
            q7 = [q for *_, q in data]
            res = {}
            res['noisy_clip7'] = dict(mean=float(np.mean([psnr(c, q) for c, q in zip(clean, q7)])))
            res['noisy_raw'] = dict(mean=float(np.mean([psnr(c, r) for c, r in zip(clean, raws)])))
            configs = [('clip7_sigma25', q7, 25), ('raw_sigma25', raws, 25)]
            if best != 25:
                configs.append((f'clip7_sigma{best}', q7, best))
            for key, inputs, s in configs:
                t0 = time.time()
                den = bm3d_many(pool, inputs, s/255.0)
                per = {n: float(psnr(c, d)) for n, c, d in zip(names, clean, den)}
                res[key] = dict(sigma_psd=s, mean=float(np.mean(list(per.values()))), per_image=per,
                                seconds=round(time.time()-t0, 1))
                log(f'{set_name:<6} {key:<16} {res[key]["mean"]:6.3f} dB  ({time.time()-t0:.0f} s)')
                out['sets'][set_name] = res
                out_path.write_text(json.dumps(out, indent=2))
    if best == 25:
        for s in out['sets'].values():
            s['clip7_tuned'] = dict(s['clip7_sigma25'], note='tuned sigma == 25, same run as clip7_sigma25')
    out_path.write_text(json.dumps(out, indent=2))

    # compare with the paper's baselines.json (same protocol -> should match item 1)
    bl = REPO/'denoise'/'baselines.json'
    if bl.exists():
        b = json.loads(bl.read_text())
        for set_name in ('Set12', 'BSD68'):
            log(f'{set_name:<6} baselines.json bm3d = {b["sets"][set_name]["bm3d"]["mean"]:.3f} dB; '
                f'this run clip7_sigma25 = {out["sets"][set_name]["clip7_sigma25"]["mean"]:.3f} dB')

    # per-image wins against the quality model, only if its integer eval exists
    ie = REPO/'denoise'/'export'/'dn_d10_c64_us_es_qat'/'int_eval.json'
    if ie.exists():
        log(f'found {ie}; per-image comparison not implemented here (format unknown)')
    else:
        log(f'{ie} does not exist -> per-image wins vs B+QAT skipped')
    log(f'wrote {out_path}')
    return out


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode in ('sweep', 'all'):
        sweep()
    if mode in ('test', 'all'):
        test()
