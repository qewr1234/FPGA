"""Fig. 1 of PAPER_EN.md: the system, and where the three layouts act.

    python3 bankperm/figures/fig_system.py      # writes fig_system.png and fig_system.pdf here

A schematic, not data: the host builds each layer's windows (im2col), puts every
tap in a slot, and the slot decides the bank (slot j -> bank j mod 4); the core's
four banks skip zero taps but advance in lockstep, so a window costs the fullest
bank's count m, as in equation (1). The relabeling (L1, and L3's) and the skew's
weight-column order are folded into the weights offline; the host applies the skew's
slot order to every window. The bitstream
is the same for every layout. The example window (16 taps, 4, 1, 3 and 2 nonzeros per bank) is drawn, not taken from a run.
Drawn at 8.0 cm, the width the build places it at (build_docx --col-fig-cm 8), with
the colours and fonts of fig1_layouts.py.
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['hatch.linewidth'] = 0.4
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

from fig1_layouts import BANK, DOTTED, INK, MUTED, ZERO, setup_fonts

HERE = Path(__file__).resolve().parent
W_CM, H_CM = 8.0, 4.0
FILL = '#f7f6f3'                       # box background
EDGE = '#9a9893'


def box(ax, x, y, w, h, title):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=0.12', fc=FILL, ec=EDGE,
                                lw=0.6, zorder=1))
    ax.text(x + 0.12, y + h - 0.1, title, ha='left', va='top', fontsize=7, fontweight='bold', color=INK, zorder=3)


def arrow(ax, p, q, text=None, dy=0.1, rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=6, lw=0.7, color=INK,
                                 connectionstyle=f'arc3,rad={rad}', zorder=4))
    if text:
        ax.text((p[0] + q[0])/2, (p[1] + q[1])/2 + dy, text, ha='center', va='bottom', fontsize=5.5,
                color=MUTED, zorder=5)


def main():
    setup_fonts()
    fs = 6.0
    fig = plt.figure(figsize=(W_CM/2.54, H_CM/2.54), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W_CM); ax.set_ylim(0, H_CM); ax.axis('off')

    # --- host: what it does per layer; the layouts act only here
    hx, hy, hw, hh = 0.04, 0.04, 3.1, H_CM - 0.08
    box(ax, hx, hy, hw, hh, 'Host (PC)')
    steps = ['offline, into the weights:\nthe relabeling (L1, L3) and\nthe skew order (L2, L3)',
             'per layer: im2col, window of\nK = 9N taps; tap (s, p) → slot',
             'skew (L2, L3): tap (s, p) to\nslot s·N + (p + s) mod N',
             'requantize the sums;\nnext layer']
    y, gap = hy + hh - 0.36, 0.14
    heights = (0.92, 0.7, 0.7, 0.62)
    centers = []
    for i, what in enumerate(steps):
        h = heights[i]
        ax.add_patch(Rectangle((hx + 0.1, y - h), hw - 0.2, h, fc='white', ec=EDGE, lw=0.5, zorder=2))
        ax.text(hx + 0.17, y - h/2, what, ha='left', va='center', fontsize=fs, color=INK, linespacing=1.2, zorder=3)
        centers.append(y - h/2)
        if i in (1, 2):
            arrow(ax, (hx + hw/2, y - h), (hx + hw/2, y - h - gap))
        y -= h + gap

    # --- core: one bitstream for every layout
    cx, cy, cw, ch = 3.92, 0.04, W_CM - 3.96, H_CM - 0.08
    box(ax, cx, cy, cw, ch, 'FPGA core (one bitstream)')
    ax.text(cx + 0.12, cy + ch - 0.4, 'window: slot j → bank j mod 4', ha='left', va='top', fontsize=fs, color=INK)
    nz = [1, 0, 1, 1, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0]     # a drawn example: 1 = nonzero (banks 4, 1, 3, 2)
    n_show, s = 16, 0.225
    sx, sy = cx + 0.14, cy + ch - 1.0
    for j in range(n_show):
        ax.add_patch(Rectangle((sx + j*s, sy), s*0.88, s*0.88, fc=BANK[j % 4] if nz[j] else ZERO, ec=EDGE,
                               lw=0.3, zorder=3))
        if nz[j] and j % 4 == DOTTED:   # the white dot of Fig. 2 (grayscale)
            ax.plot(sx + j*s + s*0.44, sy + s*0.44, 'o', ms=1.4, mfc='white', mec='none', zorder=4)
    ax.text(sx, sy - 0.06, 'example window, 16 taps; filled: nonzero', ha='left', va='top', fontsize=5.5, color=MUTED)
    counts = [sum(nz[b::4]) for b in range(4)]
    bw, bg, unit = 0.36, 0.10, 0.22
    bx0, by0 = cx + 0.6, cy + 0.98
    for b, n in enumerate(counts):
        x = bx0 + b*(bw + bg)
        ax.add_patch(Rectangle((x, by0), bw, n*unit, fc=BANK[b], ec=INK if n == max(counts) else 'none', lw=0.7,
                               zorder=3))
        if n < max(counts):   # the cycles this bank waits for the fullest one
            ax.add_patch(Rectangle((x, by0 + n*unit), bw, (max(counts) - n)*unit, fc='white', ec=MUTED, lw=0.4,
                                   hatch='/////', zorder=2))
        ax.text(x + bw/2, by0 - 0.06, str(b), ha='center', va='top', fontsize=fs, color=INK)
        ax.text(x + bw/2, by0 + n*unit - 0.03, str(n), ha='center', va='top', fontsize=fs,
                color='white' if b < 2 else INK, zorder=4)
    ax.text(bx0 - 0.08, by0 - 0.06, 'bank', ha='right', va='top', fontsize=fs, color=INK)
    m = max(counts); top = by0 + m*unit; right = bx0 + 4*(bw + bg) - bg
    ax.plot([bx0 - 0.06, right + 0.06], [top, top], ls=(0, (2, 1.5)), lw=0.6, color=INK, zorder=4)
    ax.text(right + 0.14, top + 0.03, 'lockstep: all\nbanks wait for\nthe fullest, m\n(hatched: idle)', ha='left', va='top',
            fontsize=fs, color=INK, linespacing=1.15)
    ax.text(cx + 0.12, cy + 0.44, 'each bank skips its zero taps', ha='left', va='center', fontsize=fs, color=INK)
    ax.text(cx + 0.12, cy + 0.2, 'window: max(load, 2m, COUT) cycles (1)', ha='left', va='center', fontsize=fs,
            color=INK)

    # --- data paths between host and core
    arrow(ax, (hx + hw, centers[0]), (cx, centers[0]), 'weights', dy=0.03)
    arrow(ax, (hx + hw, centers[2]), (cx, centers[2]), 'windows', dy=0.03)
    arrow(ax, (cx, centers[3]), (hx + hw, centers[3]), 'sums', dy=0.03)

    out = HERE/'fig_system'
    fig.savefig(out.with_suffix('.png'), dpi=300)
    fig.savefig(out.with_suffix('.pdf'))
    print('wrote', out.with_suffix('.png'), out.with_suffix('.pdf'))


if __name__ == '__main__':
    main()
