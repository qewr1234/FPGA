"""SSIM next to PSNR for the paper's denoisers and references.

    python denoise/ssim_eval.py                         # paper models + BM3D + DnCNN-S -> denoise/ssim_eval.json
    python denoise/ssim_eval.py --models dn_d7_c32_es   # some exports only (merged into the file)
    python denoise/ssim_eval.py --no-bm3d --no-dncnn

SSIM is that of Wang et al. (2004) on 8-bit images: an 11x11 Gaussian window
with sigma 1.5, K1 = 0.01, K2 = 0.03 and a data range of 255, averaged over the
image (skimage.metrics.structural_similarity with gaussian_weights=True and
use_sample_covariance=False, the settings that reproduce the reference code).
Float outputs (BM3D, DnCNN-S) are rounded to 8 bits first; the integer models
already output 8 bits.

Every output is rebuilt from the seed-0 noise the PSNR tables use, and each
image's PSNR is checked against the stored value before its SSIM is kept: the
integer models run through the board driver's host emulation
(scripts/run_denoise.py, the arithmetic the board reproduces bit for bit) and
must match int_eval.json to 1e-5 dB (the images agree to the pixel, but
common.psnr averages in float32 and another PC's numpy rounds that sum
differently, by up to about 2e-6 dB; the largest gap is recorded per model);
BM3D must match baselines.json (clipped
7-bit input) and bm3d_protocol.json (unclipped) to 1e-3 dB; DnCNN-S must match
dncnn_s_protocol.json to 1e-3 dB.
"""
import os
for _v in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import argparse
import contextlib
import io
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from skimage.metrics import structural_similarity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT/'scripts'))
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402

SIGMA = 25
SETS = ('Set12', 'BSD68')
MODELS = ['dn_d7_c32_es', 'dn_d10_c64_us_es', 'dn_d10_c64_us_es_qat',
          'dn_d10_c32_us_fx', 'dn_d10_c32_us_fx_qat', 'dn_d10_c32_us_mo_fx', 'dn_d10_c32_us_mo_fx_qat',
          'dn_d10_c32_us_avg_fx', 'dn_d10_c32_us_avg_fx_qat', 'dn_d10_c32_us_mo_es_qat',
          'dn_d10_c32_us_fx_s2_qat', 'dn_d10_c32_us_fx_s3_qat', 'dn_d10_c32_us_mo_fx_s2_qat', 'dn_d10_c32_us_mo_fx_s3_qat',
          'dn_d10_c32_us_avg_fx_s2_qat', 'dn_d10_c45_us_fx_qat']
DNCNN_WEIGHTS = Path('/home/user/tools/DnCNN/TrainingCodes/dncnn_pytorch/models/DnCNN_sigma25/model.pth')
OUT = HERE/'ssim_eval.json'


def ssim(clean, out_u8):
    ref = np.uint8(np.rint(clean*255))
    return float(structural_similarity(ref, out_u8, data_range=255, gaussian_weights=True, sigma=1.5,
                                       use_sample_covariance=False))


def to_u8(x):
    return np.uint8(np.clip(np.rint(x*255), 0, 255))


def record(res, set_name, key, per_ssim, per_psnr):
    res['sets'].setdefault(set_name, {})[key] = dict(
        ssim=float(np.mean(list(per_ssim.values()))), psnr=float(np.mean(list(per_psnr.values()))),
        per_image_ssim=per_ssim)


def one_model(name):
    """SSIM of one export's integer model on both test sets, checked against its int_eval.json."""
    import run_denoise
    export = HERE/'export'/name
    man, layers = run_denoise.load_layers(export)
    ev = json.loads((export/'int_eval.json').read_text())
    args = SimpleNamespace(emulate=True, out=None)
    out, dev = {}, 0.0
    for set_name in SETS:
        per_s, per_p = {}, {}
        for n, clean, noisy in test_noise(load_set(set_name), man['sigma'], seed=0):
            q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
            with contextlib.redirect_stdout(io.StringIO()):     # the driver prints every layer
                img, _ = run_denoise.denoise(q_in, man, layers, args, Path(n).stem)
            p = psnr(clean, img.astype(np.float32)/255)
            dev = max(dev, abs(p - ev[set_name]['per_image'][n]))
            if abs(p - ev[set_name]['per_image'][n]) > 1e-5:
                raise SystemExit(f'{name} {n}: {p:.6f} dB here, {ev[set_name]["per_image"][n]:.6f} in int_eval.json')
            per_s[n], per_p[n] = ssim(clean, img), p
        out[set_name] = (per_s, per_p)
    return name, out, dev


def _bm3d(x):
    import bm3d
    return bm3d.bm3d(x, sigma_psd=SIGMA/255.0)


def bm3d_refs(res, pool):
    from bm3d_protocol import test_noise_raw
    base = json.loads((HERE/'baselines.json').read_text())['sets']
    prot = json.loads((HERE/'bm3d_protocol.json').read_text())['sets']
    for set_name in SETS:
        data = test_noise_raw(load_set(set_name), SIGMA, seed=0)
        for key, pick, ref in (('bm3d_clip7', lambda d: d[3], base[set_name]['bm3d']['per_image']),
                               ('bm3d_unclipped', lambda d: d[2], prot[set_name]['raw_sigma25']['per_image'])):
            t0 = time.time()
            den = pool.map(_bm3d, [pick(d) for d in data], chunksize=1)
            per_s, per_p = {}, {}
            for (n, c, *_), d in zip(data, den):
                p = psnr(c, d)
                if abs(p - ref[n]) > 1e-3:
                    raise SystemExit(f'{key} {set_name} {n}: {p:.4f} dB here, {ref[n]:.4f} stored')
                per_s[n], per_p[n] = ssim(c, to_u8(d)), p
            record(res, set_name, key, per_s, per_p)
            print(f'{set_name:<6} {key:<16} SSIM {res["sets"][set_name][key]["ssim"]:.4f}  ({time.time()-t0:.0f} s)', flush=True)
            OUT.write_text(json.dumps(res, indent=2))


def dncnn_ref(res):
    import torch
    from dncnn_s_protocol import load, noisy_pairs
    torch.set_num_threads(4)
    model = load(DNCNN_WEIGHTS)
    stored = json.loads((HERE/'dncnn_s_protocol.json').read_text())['sets']
    for set_name in SETS:
        per_s, per_p = {}, {}
        with torch.no_grad():
            for n, c, raw, q7 in noisy_pairs(load_set(set_name), SIGMA):
                d = model(torch.from_numpy(np.ascontiguousarray(q7, dtype=np.float32))[None, None])[0, 0].numpy()
                p = psnr(c, d)
                if abs(p - stored[set_name]['clip7']['per_image'][n]) > 1e-3:
                    raise SystemExit(f'DnCNN-S {set_name} {n}: {p:.4f} dB here, '
                                     f'{stored[set_name]["clip7"]["per_image"][n]:.4f} stored')
                per_s[n], per_p[n] = ssim(c, to_u8(d)), p
        record(res, set_name, 'dncnn_s_clip7', per_s, per_p)
        print(f'{set_name:<6} DnCNN-S clip7     SSIM {res["sets"][set_name]["dncnn_s_clip7"]["ssim"]:.4f}', flush=True)
        OUT.write_text(json.dumps(res, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', help='comma separated exports (default: the paper\'s, where exported)')
    ap.add_argument('--no-bm3d', action='store_true')
    ap.add_argument('--no-dncnn', action='store_true')
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--skip-done', action='store_true', help='leave out models already in the file')
    args = ap.parse_args()
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    res.update(sigma=SIGMA, seed=0,
               ssim='Wang et al. 2004: 11x11 Gaussian window, sigma 1.5, K1 0.01, K2 0.03, range 255, 8-bit images')
    res.setdefault('sets', {})
    names = args.models.split(',') if args.models else [m for m in MODELS if (HERE/'export'/m/'manifest.json').exists()]
    if args.skip_done:
        names = [m for m in names if m not in res['sets'].get('BSD68', {})]
    with Pool(args.procs) as pool:
        for name, out, dev in pool.imap_unordered(one_model, names):
            for set_name, (per_s, per_p) in out.items():
                record(res, set_name, name, per_s, per_p)
            res.setdefault('max_psnr_gap_vs_int_eval_db', {})[name] = dev
            print(f'{name:<26} SSIM Set12 {res["sets"]["Set12"][name]["ssim"]:.4f}  '
                  f'BSD68 {res["sets"]["BSD68"][name]["ssim"]:.4f}', flush=True)
            OUT.write_text(json.dumps(res, indent=2))
        if not args.no_bm3d:
            bm3d_refs(res, pool)
    if not args.no_dncnn:
        dncnn_ref(res)
    OUT.write_text(json.dumps(res, indent=2))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
