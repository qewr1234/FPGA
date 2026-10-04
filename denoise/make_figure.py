"""Side-by-side figure: clean, noisy, Gaussian, BM3D, and this denoiser.

    python denoise/make_figure.py --model dn_d7_c32 --image 05.png
    python denoise/make_figure.py --model dn_d7_c32 --image 05.png --board build/denoise_run

Every panel is computed here on the same noisy image (common.test_noise, seed 0)
except, with --board, the last one: then it is the picture the FPGA produced,
read from run_denoise.py's output, and its title says so. Without --board the
last panel is the integer model -- what the board will compute, bit for bit,
but not a board result -- and its title says that instead. A crop (--crop) is
shown enlarged underneath, because at full size the differences are small.

Writes denoise/figures/<image>_<model>[_board].png and .pdf.
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

from common import HERE, QMAX_A, load_set, psnr, test_noise

sys.path.insert(0, str(HERE.parent/'scripts'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='dn_d7_c32')
    ap.add_argument('--set', default='Set12')
    ap.add_argument('--image', default='05.png')
    ap.add_argument('--board', type=Path, help='run_denoise.py output directory of a BOARD run')
    ap.add_argument('--crop', default='auto', help='y,x,size of the enlarged crop, or auto')
    args = ap.parse_args()

    base = json.loads((HERE/'baselines.json').read_text())
    tests = {n: (c, x) for n, c, x in test_noise(load_set(args.set), base['sigma'], seed=0)}
    if args.image not in tests:
        raise SystemExit(f'{args.image} is not in {args.set}')
    clean, noisy = tests[args.image]

    import bm3d
    gauss = gaussian_filter(noisy, base['gaussian_sigma'])
    b3 = bm3d.bm3d(noisy, sigma_psd=base['sigma']/255.0)

    if args.board:
        rep = json.loads((args.board/'report.json').read_text())
        if rep['emulated']:
            raise SystemExit(f'{args.board} holds an EMULATED run; --board needs a board run')
        ours = np.asarray(Image.open(args.board/f'{Path(args.image).stem}_denoised.png'),
                          np.float32)/255
        ours_title = 'FPGA board (this work)'
    else:
        from run_denoise import denoise, load_layers
        man, layers = load_layers(HERE/'export'/args.model)
        ns = argparse.Namespace(emulate=True)
        out, _ = denoise(np.rint(noisy*QMAX_A).astype(np.uint8), man, layers, ns, 'fig')
        ours = out.astype(np.float32)/255
        ours_title = 'this work (integer model)'

    panels = [('clean', clean, None), (f'noisy  sigma={base["sigma"]:.0f}', noisy, psnr(clean, noisy)),
              (f'Gaussian blur', gauss, psnr(clean, gauss)), ('BM3D', b3, psnr(clean, b3)),
              (ours_title, ours, psnr(clean, ours))]

    h, w = clean.shape
    if args.crop == 'auto':
        s = min(h, w)//4
        # The crop where the clean image has the most detail, so the methods differ.
        best, cy, cx = -1, 0, 0
        for y in range(0, h-s+1, s//2):
            for x in range(0, w-s+1, s//2):
                v = float(np.var(clean[y:y+s, x:x+s]))
                if v > best:
                    best, cy, cx = v, y, x
    else:
        cy, cx, s = map(int, args.crop.split(','))

    fig, ax = plt.subplots(2, len(panels), figsize=(3.2*len(panels), 6.6))
    for j, (t, im, p) in enumerate(panels):
        ax[0, j].imshow(np.clip(im, 0, 1), cmap='gray', vmin=0, vmax=1)
        ax[0, j].set_title(t + ('' if p is None else f'\n{p:.2f} dB'), fontsize=10)
        ax[0, j].add_patch(plt.Rectangle((cx, cy), s, s, fill=False, ec='#e4572e', lw=1.2))
        ax[1, j].imshow(np.clip(im[cy:cy+s, cx:cx+s], 0, 1), cmap='gray', vmin=0, vmax=1,
                        interpolation='nearest')
        for a in ax[:, j]:
            a.set_xticks([]); a.set_yticks([])
    fig.suptitle(f'{args.set} {args.image}, AWGN sigma {base["sigma"]:.0f} clipped to [0,1], '
                 f'7-bit input -- every method on the same noisy image', fontsize=10)
    fig.tight_layout()
    out_dir = HERE/'figures'
    out_dir.mkdir(exist_ok=True)
    stem = f'{Path(args.image).stem}_{args.model}{"_board" if args.board else ""}'
    for ext in ('png', 'pdf'):
        fig.savefig(out_dir/f'{stem}.{ext}', dpi=150)
    print(f'wrote {out_dir/stem}.png / .pdf')
    for t, _, p in panels[1:]:
        print(f'  {t.splitlines()[0]:<28} {p:.2f} dB')


if __name__ == '__main__':
    main()
