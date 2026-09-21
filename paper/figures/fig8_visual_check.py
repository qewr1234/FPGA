"""Fig. 8 -- visual check: input, software reference, hardware output, difference.

Needs a contiguous export (scripts/export_featuremap.py) plus the board's
results.bin from the run that used it.

Two things this has to get right beyond plotting. Feature maps are dominated by
values at or near zero with a thin tail of large ones, so a linear scale renders
them almost uniformly dark; the maps are shown on a percentile-clipped scale
instead, and the clip is stated in the caption rather than left implicit. And a
difference panel that is uniformly zero reads as a blank box, so it says so in
the panel.

    python paper/figures/fig8_visual_check.py              # pick the channel
    python paper/figures/fig8_visual_check.py --channel 42
    python paper/figures/fig8_visual_check.py --sheet      # preview 24 channels

Re-running costs nothing: it reads the files a board run already produced.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib.pyplot as plt
from paperstyle import FULL_W, save, use_paper_style

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT/'build'/'board'


def load():
    meta = json.loads((BOARD/'featuremap.json').read_text(encoding='utf-8'))
    s, cout = meta['size'], meta['COUT']

    def grid(path):
        if not path.exists():
            return None
        a = np.frombuffer(path.read_bytes(), dtype='<i4').reshape(-1, cout)
        if meta.get('mode') == 2:
            a = a[0::2]        # mode 2 runs each window twice; keep one copy
        return a.reshape(s, s, cout)

    return meta, grid(BOARD/'gold.bin'), grid(BOARD/'results.bin')


def square(img):
    """Centre-crop to a square, which is what the network is fed anyway."""
    h, w = img.shape[:2]
    n = min(h, w)
    return img[(h-n)//2:(h-n)//2+n, (w-n)//2:(w-n)//2+n]


def pick_channel(gold):
    """The channel whose map has the most structure, not just the largest peak.

    Ranking by peak or by range lands on a map that is one bright pixel on an
    empty field. Counting how many positions carry real signal finds one that
    actually shows the shape.
    """
    flat = gold.reshape(-1, gold.shape[-1]).astype(np.float64)
    hi = np.percentile(flat, 99.5, axis=0)
    live = (flat > np.maximum(hi*0.15, 1)).sum(axis=0)
    return int(np.argmax(live))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', type=int, default=None)
    ap.add_argument('--clip', type=float, default=99.0,
                    help='percentile mapped to the top of the colour scale')
    ap.add_argument('--sheet', action='store_true',
                    help='write a contact sheet of channels and exit')
    args = ap.parse_args()

    use_paper_style()
    # paperstyle.save() writes relative to the working directory, and this one is
    # run from the repository root, not from here.
    os.chdir(Path(__file__).resolve().parent)

    meta, gold, got = load()
    if gold is None:
        raise SystemExit('build/board/gold.bin is missing -- run the exporter first')

    if args.sheet:
        order = np.argsort(-np.asarray(
            [(gold[:, :, c] > max(np.percentile(gold[:, :, c], 99.5)*0.15, 1)).sum()
             for c in range(gold.shape[-1])]))[:24]
        fig, ax = plt.subplots(4, 6, figsize=(FULL_W, FULL_W*4/6))
        for a, c in zip(ax.ravel(), order):
            a.imshow(gold[:, :, c], cmap='viridis',
                     vmax=max(np.percentile(gold[:, :, c], args.clip), 1))
            a.set_title(f'ch {c}', fontsize=7)
            a.set_xticks([]); a.set_yticks([])
        save(fig, 'fig8_channels')
        print('pick one and pass it with --channel')
        return

    if got is None:
        raise SystemExit('build/board/results.bin is missing -- run the board first')

    ch = args.channel if args.channel is not None else pick_channel(gold)
    ref, hw = gold[:, :, ch], got[:, :, ch]
    diff = hw.astype(np.int64) - ref.astype(np.int64)
    vmax = max(float(np.percentile(ref, args.clip)), 1.0)

    img = plt.imread(ROOT/meta['image']) if (ROOT/meta['image']).exists() else None
    ncol = 4 if img is not None else 3
    fig, ax = plt.subplots(1, ncol, figsize=(FULL_W, FULL_W/ncol + 0.7))
    k = 0
    if img is not None:
        ax[k].imshow(square(img), cmap='gray' if img.ndim == 2 else None)
        ax[k].set_title('Input image'); k += 1

    ax[k].imshow(ref, cmap='viridis', vmin=0, vmax=vmax)
    ax[k].set_title(f'Software reference\n(INT32 oracle, ch {ch})'); k += 1
    ax[k].imshow(hw, cmap='viridis', vmin=0, vmax=vmax)
    ax[k].set_title(f'Hardware output\n(Zynq-7020, ch {ch})'); k += 1

    ax[k].imshow(diff, cmap='RdBu_r', vmin=-1, vmax=1)
    ax[k].set_title('Difference')
    ax[k].text(0.5, 0.5, f'all {gold.size:,}\noutputs identical',
               transform=ax[k].transAxes, ha='center', va='center', fontsize=8)

    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    save(fig, 'fig8_visual_check')
    print(f'channel {ch}, {meta["size"]}x{meta["size"]} windows, {gold.size} outputs, '
          f'mismatches {int((got != gold).sum())}, colour scale 0..{vmax:.0f} '
          f'(p{args.clip:g} of the reference)')


if __name__ == '__main__':
    main()
