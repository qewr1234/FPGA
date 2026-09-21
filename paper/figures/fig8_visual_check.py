"""Fig. 8 -- visual check: input, software reference, hardware output, difference.

Needs a contiguous export (scripts/export_featuremap.py) plus the board's
results.bin from the run that used it. The difference panel is the point: it is
flat zero, and the figure says so with a number rather than asking the reader to
trust two pictures that look alike.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib.pyplot as plt
from paperstyle import FULL_W, save, setup

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT/'build'/'board'


def load():
    meta = json.loads((BOARD/'featuremap.json').read_text(encoding='utf-8'))
    s, cout = meta['size'], meta['COUT']
    gold = np.frombuffer((BOARD/'gold.bin').read_bytes(), dtype='<i4').reshape(s, s, cout)
    res = BOARD/'results.bin'
    got = (np.frombuffer(res.read_bytes(), dtype='<i4').reshape(s, s, cout)
           if res.exists() else None)
    return meta, gold, got


def main():
    setup()
    meta, gold, got = load()
    if got is None:
        raise SystemExit('build/board/results.bin is missing -- run the board first')

    ch = int(np.argmax(gold.reshape(-1, gold.shape[-1]).ptp(axis=0)))  # liveliest map
    ref, hw = gold[:, :, ch], got[:, :, ch]
    diff = hw.astype(np.int64) - ref.astype(np.int64)

    img = plt.imread(ROOT/meta['image']) if (ROOT/meta['image']).exists() else None
    ncol = 4 if img is not None else 3
    fig, ax = plt.subplots(1, ncol, figsize=(FULL_W, FULL_W/ncol + 0.55))
    k = 0
    if img is not None:
        ax[k].imshow(img, cmap='gray' if img.ndim == 2 else None)
        ax[k].set_title('Input image'); k += 1

    vmin, vmax = ref.min(), ref.max()
    ax[k].imshow(ref, cmap='viridis', vmin=vmin, vmax=vmax)
    ax[k].set_title(f'Software reference\n(INT32 oracle, ch {ch})'); k += 1
    ax[k].imshow(hw, cmap='viridis', vmin=vmin, vmax=vmax)
    ax[k].set_title(f'Hardware output\n(Zynq-7020, ch {ch})'); k += 1
    ax[k].imshow(diff, cmap='RdBu_r', vmin=-1, vmax=1)
    ax[k].set_title(f'Difference\nmax |delta| = {np.abs(diff).max()}')

    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    save(fig, 'fig8_visual_check')
    n = gold.size
    print(f'channel {ch}, {meta["size"]}x{meta["size"]} windows, '
          f'{n} outputs, mismatches {int((got != gold).sum())}')


if __name__ == '__main__':
    main()
