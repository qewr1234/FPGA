"""Fig. 2: the ten-network study, saving of the fitted relabeling at W = 2 and W = 4.

    python bankperm/figures/fig2_networks.py   # writes bankperm/figures/fig2_networks.{png,pdf}

Per network (bankperm/results.json, the Frozen recipe fitted on each network's
Set12 01.png): the pooled saving over the 79 images other than Set12 01.png
(count of conv1-convL, 100 * (original - permuted) / original) as a marker,
and the per-image minimum to maximum as a line, at W = 2 and at W = 4. Where
bankperm/bounds.json says the relabeling cannot pay (condition (2) holds for
every layer), the saving is zero by the layer shapes; that is drawn as its own
marker at 0, after checking that results.json has exactly 0 on every image
there. W = 1 is zero by shape on every network; a note says so (also checked).
Pooled values are recomputed from the per-image counts and checked against the
summaries. Short labels (printed): A, B, R1-R3, M1-M3, Av2, 45.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
BANKPERM = HERE.parent

BLUE, ORANGE, AQUA, INK, MUTED = '#2a78d6', '#eb6834', '#1baf7a', '#0b0b0b', '#52514e'
GRID = '#e6e5e1'
SHORT = {  # results.json label -> (short label, definition, x position: families set apart)
    'A': ('A', 'A, 7 layers x 32 channels', 0.0),
    'B + QAT': ('B', 'B, 10 x 64 behind 2x2 space-to-depth (QAT)', 1.0),
    'B-32 ReLU + QAT s1': ('R1', 'B-32 ReLU, training seed s1 (the board network)', 2.3),
    'B-32 ReLU + QAT s2': ('R2', 'B-32 ReLU, seed s2', 3.3),
    'B-32 ReLU + QAT s3': ('R3', 'B-32 ReLU, seed s3', 4.3),
    'B-32 maxout + QAT s1': ('M1', 'B-32 maxout, seed s1', 5.6),
    'B-32 maxout + QAT s2': ('M2', 'B-32 maxout, seed s2', 6.6),
    'B-32 maxout + QAT s3': ('M3', 'B-32 maxout, seed s3', 7.6),
    'B-32 averaging + QAT s2': ('Av2', 'B-32 averaging, seed s2', 8.9),
    '10 x 45 ReLU + QAT': ('45', '10 x 45 ReLU', 10.2),
}
CAL = 'Set12/01.png'
DX = {'w2': -0.17, 'w4': 0.17}


def setup_fonts():
    for f in ('Liberation Sans', 'Arial', 'DejaVu Sans'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'pdf.fonttype': 42, 'ps.fonttype': 42})


def stats(net, w):
    """(pooled %, min %, max %) over the 79 images, from the per-image counts; checked against the summary."""
    per = {k: v[w] for k, v in net['per_image'].items() if k != CAL}
    assert len(per) == 79
    sav = [100*(o - p)/o for o, p in per.values()]
    pooled = 100*(sum(o for o, _ in per.values()) - sum(p for _, p in per.values()))/sum(o for o, _ in per.values())
    h = net['summary'][w]['headline_79']
    assert abs(pooled - h['pooled_pct']) < 1e-9 and abs(min(sav) - h['min_pct']) < 1e-9 \
        and abs(max(sav) - h['max_pct']) < 1e-9, (net['model'], w)
    return pooled, min(sav), max(sav), [o == p for o, p in per.values()]


def main():
    setup_fonts()
    res = json.loads((BANKPERM/'results.json').read_text())['networks']
    bounds = json.loads((BANKPERM/'bounds.json').read_text())['networks']
    assert list(res) == list(SHORT) and set(bounds) == set(SHORT)

    fig, ax = plt.subplots(figsize=(8.4/2.54, 5.3/2.54), dpi=300)
    print('labels:')
    by_shape = []
    for label, (short, definition, x) in SHORT.items():
        net = res[label]
        assert bounds[label]['model'] == net['model']
        print(f'  {short:<4} {definition}  ({label}, {net["model"]})')
        p1, lo1, hi1, eq1 = stats(net, 'w1')
        assert not bounds[label]['can_pay']['w1'] and all(eq1) and p1 == 0      # W = 1: zero by shape everywhere
        for w, col, mk, fill in (('w2', BLUE, 'o', 'white'), ('w4', ORANGE, 'D', ORANGE)):
            pooled, lo, hi, eq = stats(net, w)
            xx = x + DX[w]
            if not bounds[label]['can_pay'][w]:
                assert all(eq) and pooled == 0, (label, w)                       # zero on every image, as predicted
                ax.plot(xx, 0, marker='x', ms=4.2, mew=1.1, color=col, ls='', zorder=4, clip_on=False)
                by_shape.append(f'{short} {w}')
                continue
            ax.plot([xx, xx], [lo, hi], color=col, lw=0.9, solid_capstyle='butt', zorder=2)
            ax.plot(xx, pooled, marker=mk, ms=3.6 if mk == 'D' else 4.0, mfc=fill, mec=col, mew=1.0, ls='',
                    zorder=3)
            print(f'       {w}: pooled {pooled:.3f}%  per image {lo:.3f}..{hi:.3f}%')
        if label == '10 x 45 ReLU + QAT':
            pooled = stats(net, 'w2')[0]
            ax.annotate(f'{pooled:.2f}', (x + DX['w2'], pooled), xytext=(-3.5, 0), textcoords='offset points',
                        ha='right', va='center', fontsize=7, color=INK)
    print('zero by shape (bounds.json, exactly 0 on all 79 images in results.json):', ', '.join(by_shape))
    print('W = 1: zero by shape on all ten networks, exactly 0 on every image (checked)')

    ax.set_xticks([v[2] for v in SHORT.values()])
    ax.set_xticklabels([v[0] for v in SHORT.values()])
    ax.set_xlim(-0.55, 10.75)
    ax.set_ylim(-0.6, 15.5)
    ax.set_yticks([0, 5, 10, 15])
    ax.set_ylabel('saving vs. original (%)', labelpad=2)
    ax.tick_params(length=2, pad=1.5)
    ax.grid(True, axis='y', color=GRID, lw=0.5, zorder=0)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    handles = [Line2D([], [], marker='o', color=BLUE, mfc='white', ms=4.0, lw=0.9, label='W = 2'),
               Line2D([], [], marker='D', color=ORANGE, mfc=ORANGE, ms=3.6, lw=0.9, label='W = 4'),
               Line2D([], [], marker='x', color=BLUE, ms=4.2, mew=1.1, ls='', label='W = 2: 0 by shape')]
    leg = fig.legend(handles=handles, loc='upper center', ncol=3, frameon=False, handlelength=1.4,
                     handletextpad=0.4, columnspacing=1.1, borderaxespad=0.1, bbox_to_anchor=(0.54, 1.0))
    for t in leg.get_texts():
        t.set_color(INK)
    ax.text(0.995, 0.99, 'W = 1: 0 on every\nnetwork (by shape)', transform=ax.transAxes, ha='right', va='top',
            fontsize=7, color=MUTED, linespacing=1.15)
    fig.tight_layout(pad=0.25, rect=(0, 0, 1, 0.93))
    out = HERE/'fig2_networks'
    fig.savefig(out.with_suffix('.png'), dpi=300)
    fig.savefig(out.with_suffix('.pdf'))
    print('wrote', out.with_suffix('.png'), out.with_suffix('.pdf'))


if __name__ == '__main__':
    main()
