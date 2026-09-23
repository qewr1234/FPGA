"""Fig. 9 -- what the board decided: CIFAR-10 test images under the FPGA's labels.

Every label in this figure was produced by the accelerator. The host does the
im2col, the requantization between layers, the pooling and the final linear
classifier; all 38.6 million multiply-accumulates per image happen in fabric,
and the hardware reproduced the integer model's outputs exactly, so the labels
are the network's own rather than an approximation of them.

Needs a board run's report.json (scripts/run_cifar.py) and the CIFAR-10 test
batch that quantize_cifar.py downloaded.

    python paper/figures/fig9_classified.py               # first 40 images
    python paper/figures/fig9_classified.py --count 60
    python paper/figures/fig9_classified.py --wrong       # only the misses

Misses are marked rather than hidden: a panel of nothing but correct answers
says less than one that shows what the errors look like.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib.pyplot as plt
from paperstyle import FULL_W, INK, INK2, MUTED, VERM, save, use_paper_style

ROOT = Path(__file__).resolve().parents[2]
CLASSES = ['plane', 'car', 'bird', 'cat', 'deer',
           'dog', 'frog', 'horse', 'ship', 'truck']


def load(report_path, data_dir):
    rep = json.loads(Path(report_path).read_text(encoding='utf-8'))
    if rep.get('emulated'):
        raise SystemExit(f'{report_path} is an --emulate run. This figure is '
                         f'about what the hardware decided; plotting a host '
                         f'run under that caption would be a lie.')
    batch = Path(data_dir)/'cifar-10-batches-py'/'test_batch'
    if not batch.exists():
        raise SystemExit(f'{batch} not found. Run cifar/quantize_cifar.py once '
                         f'on this machine, or copy cifar/data/ across.')
    with open(batch, 'rb') as fh:
        d = pickle.load(fh, encoding='bytes')
    n = len(rep['predictions'])
    images = d[b'data'][:n].reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1)
    pred = np.asarray(rep['predictions'])
    true = np.asarray(rep['labels'])
    if not np.array_equal(true, np.asarray(d[b'labels'][:n])):
        raise SystemExit('the report\'s labels are not the first %d of the test '
                         'set, so the images cannot be lined up with them' % n)
    return rep, images, pred, true


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--report', default=ROOT/'build'/'cifar_run'/'report.json')
    ap.add_argument('--data', default=ROOT/'cifar'/'data')
    ap.add_argument('--count', type=int, default=40, help='images to show')
    ap.add_argument('--cols', type=int, default=10)
    ap.add_argument('--wrong', action='store_true', help='show only the misses')
    args = ap.parse_args()

    rep, images, pred, true = load(args.report, args.data)
    ok = pred == true
    idx = np.flatnonzero(~ok) if args.wrong else np.arange(len(pred))
    if len(idx) == 0:
        raise SystemExit('nothing to show')
    idx = idx[:args.count]
    cols = min(args.cols, len(idx))
    rows = (len(idx)+cols-1)//cols

    use_paper_style()
    # Each tile is a 32x32 image plus one line of label underneath.
    tile = FULL_W/cols
    fig, axes = plt.subplots(rows, cols, figsize=(FULL_W, rows*tile*1.34))
    axes = np.atleast_2d(axes)
    for k, ax in enumerate(axes.ravel()):
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        if k >= len(idx):
            ax.set_visible(False)
            continue
        i = idx[k]
        ax.imshow(images[i])
        # Every label is two lines tall, the second one empty when the answer
        # was right. A miss needs both names -- what it said and what it was --
        # and uniform height is what stops those second lines from being
        # clipped by the row beneath.
        if ok[i]:
            ax.set_xlabel(f'{CLASSES[pred[i]]}\n ', color=INK,
                          fontsize=6.5, labelpad=2)
        else:
            ax.set_xlabel(f'{CLASSES[pred[i]]}\nnot {CLASSES[true[i]]}',
                          color=VERM, fontsize=6.5, labelpad=2)
            for s in ax.spines.values():
                s.set_visible(True)
                s.set_color(VERM)
                s.set_linewidth(0.9)

    correct, n = int(ok.sum()), len(ok)
    # Both totals come from the per-layer records, which is where the run script
    # puts them. Reading a top-level "mismatches" that a report does not carry
    # is how the first version of this figure failed.
    try:
        outputs = sum(r['windows']*r['COUT'] for r in rep['layers'])
        mismatches = sum(r['mismatches'] for r in rep['layers'])
    except (KeyError, TypeError) as e:
        raise SystemExit(f'{args.report} does not have the per-layer fields this '
                         f'figure counts from ({e}). It should be a report.json '
                         f'written by scripts/run_cifar.py.')
    # Two lines on purpose: one of these at 7.5 pt overruns a 7.16 in page, and
    # a title that runs off the column is worse than one that takes two lines.
    fig.suptitle(
        f'Every label produced by the accelerator\n'
        f'{correct} of {n} test images correct ({correct/n:.1%});  '
        f'{mismatches} of {outputs:,} outputs differed from the integer model',
        fontsize=7.5, color=INK2, linespacing=1.5)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    # tight_layout leaves a row gap sized for axes that have titles; these have
    # a one-line label under a square image and need much less.
    fig.subplots_adjust(hspace=0.44, wspace=0.06)
    stem = str(Path(__file__).resolve().with_name(
        'fig9_classified' + ('_wrong' if args.wrong else '')))
    save(fig, stem)
    print(f'  {correct}/{n} correct, showing {len(idx)} '
          f'{"misses" if args.wrong else "images"}')


if __name__ == '__main__':
    main()
