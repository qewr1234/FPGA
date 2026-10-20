"""Fig. 1: one real window of the board network under four tap-to-bank layouts.

    python bankperm/figures/fig1_layouts.py    # writes bankperm/figures/fig1_layouts.{png,pdf}

The window is an input window of conv5 of B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat;
K = 288 = 9 positions x 32 channels, COUT = 32) on Set12 05.png, sigma 25 (the
manifest's), test_noise seed 0, captured from the board driver's host emulation
by denoise/predict_w4.layer_windows. Choice rule (stated, not tuned): among the
windows that are compute-bound at W = 4 in the conventional layout
(2*max(1, m) > the load ceil(288/4) + 1 = 73), the first in raster order whose
fullest-bank count m equals the lower median of m over those windows. The
script prints which window that is.

Each row is the same window under one layout: a 9 x 32 grid (rows: the 3x3
positions s = ky*3 + kx; columns: the channels p in their original order), a
cell filled with the colour of its bank if the activation is nonzero and left
light if it is zero (bank 1 cells also carry a white dot, so that banks 0, 1
and 2 differ in a grayscale print); beside it the nonzero taps per bank, the
fullest bank (m) outlined and labelled, against the dashed level m = 36.5
(tick '36.5') at which the compute 2*max(1, m) equals the W = 4 load of 73
cycles. A bar whose number would cross the dashed line carries it inside the
bar instead. Drawn at 8.0 cm, the width the build places it at (7 pt text at
print size). Layouts:
  (a) conventional, tap s*32 + p in bank (s*32 + p) % 4 = p % 4;
  (b) L1 relabeling (the board's L1): bank = the channel's class in
      research/q1_codesign/bank_export_perm.json (orders of conv5's producer,
      conv4; position q of the order holds channel orders[q], class q % 4);
  (c) skewed (bankperm/skew_count.py): bank (p + s) % 4;
  (d) skew + relabeling (PROTOCOL_2's L3, bankperm/perms_2.json): bank = (class of p + s) % 4,
      the class from L3's order of conv5's producer; the core sees slot s*32 + (q + s) % 32
      holding original tap s*32 + order[q] (relabeling folded, then the skew).
Checks before plotting: the class maps equal bankperm/perms.json's and perms_2.json's for conv5,
and for every layout the per-bank counts read off the grid equal those of the
column-permuted window (fit.permuted_columns, skew_count.skew_order) and the
window's cycles from predict_w4.window_cycles.

Colours: the repo's validated BLUE and AQUA, the reference palette's yellow
(slot 4) and the neutral MUTED gray, chosen so that the four banks also differ
in lightness (OKLab L 0.44 / 0.58 / 0.67 / 0.76); validated all-pairs (worst
CVD Delta E 9.1, normal vision 21.8). In grayscale banks 0 / 1 and 1 / 2 are
close, hence the dot on bank 1.
"""
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import to_rgb

HERE = Path(__file__).resolve().parent
BANKPERM = HERE.parent
ROOT = BANKPERM.parent
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts'), str(BANKPERM)]
from predict_w4 import T, layer_windows, window_cycles  # noqa: E402
from fit import permuted_columns  # noqa: E402
from skew_count import skew_order  # noqa: E402

BLUE, ORANGE, AQUA, INK, MUTED = '#2a78d6', '#eb6834', '#1baf7a', '#0b0b0b', '#52514e'
YELLOW = '#eda100'                      # reference palette slot 4
BANK = (MUTED, BLUE, AQUA, YELLOW)      # bank 0..3, increasing lightness
ZERO = '#f5f4f1'                        # zero activation
DOTTED = 1                              # bank whose cells carry a white dot (grayscale)
LABEL_IN = {0: 'white', 1: 'white', 2: INK, 3: INK}   # number colour inside a bar of each bank
WIDTH_CM = 8.0                          # final width in the paper (build_docx --col-fig-cm 8)
MODEL, LAYER, W = 'dn_d10_c32_us_fx_qat', 'conv5', 4


def setup_fonts():
    for f in ('Liberation Sans', 'Arial', 'DejaVu Sans'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'xtick.color': INK,
                         'ytick.color': INK, 'pdf.fonttype': 42, 'ps.fonttype': 42})


def choose_window(x, k, cout):
    """Index of the window chosen by the rule of the docstring, the median and the pool size."""
    load = math.ceil(k/W) + 1
    m = np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1).max(1)
    bound = math.ceil(cout/16)*np.maximum(m, 1) > max(load, cout)
    pool = np.sort(m[bound])
    med = int(pool[(len(pool) - 1)//2])
    idx = int(np.flatnonzero(bound & (m == med))[0])
    return idx, med, int(bound.sum())


def main():
    setup_fonts()
    got, (h, w_img) = layer_windows(MODEL)
    L, x = next((L, x) for L, x in got if L['name'] == LAYER)
    k, cout = L['K'], L['COUT']
    taps = L['kh']*L['kw']
    c = k // taps
    assert taps*c == k == 288 and cout == 32 and len(L['inputs']) == 1
    side = w_img // 2                                        # 2x2 space-to-depth input: the map is 128 x 128
    assert x.shape[0] == (h//2)*side
    idx, med, n_bound = choose_window(x, k, cout)
    win = x[idx]
    oy, ox = divmod(idx, side)
    load = math.ceil(k/W) + 1

    producer = L['inputs'][0]
    order = np.asarray(json.loads((ROOT/'research'/'q1_codesign'/'bank_export_perm.json').read_text())
                       ['orders'][producer])
    cls = np.empty(c, np.int64)
    cls[order] = np.arange(c) % T                            # position q holds channel order[q]: class q % 4
    perms = json.loads((BANKPERM/'perms.json').read_text())['networks']['B-32 ReLU + QAT s1']
    rec = next(f for f in perms['fitted'] if f['layer'] == LAYER)
    assert rec['producer'] == producer and cls.tolist() == rec['class_of_original_channel']

    perms2 = json.loads((BANKPERM/'perms_2.json').read_text())['networks']['B-32 ReLU + QAT s1']
    rec3 = next(f for f in perms2['fitted'] if f['layer'] == LAYER)
    order3 = np.asarray(perms2['orders'][producer])
    assert rec3['producer'] == producer and order3.tolist() == rec3['order']
    cls3 = np.asarray(rec3['class_of_original_channel'])
    assert (cls3[order3] == np.arange(c) % T).all()                 # position q of L3's order: class q % 4
    cols3 = np.empty(k, np.int64)                                    # the window the core sees under L3
    for s in range(taps):
        for q in range(c):
            cols3[s*c + (q + s) % c] = s*c + order3[q]
    s_idx, p_idx = np.meshgrid(np.arange(taps), np.arange(c), indexing='ij')     # (9, 32)
    layouts = [
        ('(a) L0: bank p mod 4', p_idx % T, np.arange(k)),
        ('(b) L1 relabeling: bank = class', cls[p_idx], permuted_columns(order, taps)),
        ('(c) L2 skew: bank (p + s) mod 4', (p_idx + s_idx) % T, skew_order(k, c)),
        ('(d) L3: bank (class + s) mod 4', (cls3[p_idx] + s_idx) % T, cols3),
    ]
    nz = win.reshape(taps, c) != 0
    rows = []
    for title, bank, cols in layouts:
        per_bank = np.array([(nz & (bank == b)).sum() for b in range(T)])
        xp = win[cols]
        assert per_bank.tolist() == [int((xp[b::T] != 0).sum()) for b in range(T)], title
        m = int(per_bank.max())
        cyc = int(window_cycles(xp[None], k, cout, W)[0])
        assert cyc == max(load, math.ceil(cout/16)*max(1, m), cout), title
        rows.append((title, bank, per_bank, m, cyc))

    moved = int((cls != np.arange(c) % T).sum())
    print(f'window: {LAYER} input, index {idx} of {x.shape[0]} (map row {oy}, column {ox} of {h//2} x {side}), '
          f'{int(nz.sum())} of {k} taps nonzero; rule: first in raster order with conventional m = {med}, '
          f'the lower median over the {n_bound} windows compute-bound at W = {W}')
    print(f'L1 relabeling of {LAYER}: {moved} of {c} channels in a class other than p mod 4')
    for title, _, per_bank, m, cyc in rows:
        print(f'  {title:<44} per bank {per_bank.tolist()}  m = {m}  cycles {cyc} '
              f'(predict_w4.window_cycles; load {load})')
    print(f'  perfect balance for this window: ceil({int(nz.sum())}/4) = {math.ceil(nz.sum()/T)}')

    fig = plt.figure(figsize=(WIDTH_CM/2.54, 8.4/2.54), dpi=300)
    gs = fig.add_gridspec(len(rows), 2, width_ratios=[32, 11], wspace=0.24, hspace=0.62,
                          left=0.085, right=0.975, top=0.945, bottom=0.095)
    zero = np.array(to_rgb(ZERO))
    pal = np.array([to_rgb(col) for col in BANK])
    ymax = 62
    for r, (title, bank, per_bank, m, cyc) in enumerate(rows):
        ax = fig.add_subplot(gs[r, 0])
        img = np.where(nz[..., None], pal[bank], zero)
        ax.imshow(img, interpolation='nearest', aspect='equal', extent=(-0.5, c - 0.5, taps - 0.5, -0.5))
        for v in np.arange(-0.5, c, 1):                      # white gaps between cells
            ax.axvline(v, color='white', lw=0.35)
        for v in np.arange(-0.5, taps, 1):
            ax.axhline(v, color='white', lw=0.35)
        dy, dx = np.nonzero(nz & (bank == DOTTED))
        ax.plot(dx, dy, ls='', marker='o', ms=0.9, mfc='white', mec='none', zorder=3)
        ax.set_xticks([0, 8, 16, 24, 31])
        ax.set_yticks([0, 4, 8])
        ax.tick_params(length=2, pad=1.5)
        if r < len(rows) - 1:
            ax.set_xticklabels([])
        else:
            ax.set_xlabel('channel p (original order)', labelpad=1.5)
        ax.set_ylabel('s', labelpad=3, rotation=0, va='center', ha='right')
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.text(-0.5, -0.95, title, fontsize=7, color=INK, ha='left', va='bottom')

        bx = fig.add_subplot(gs[r, 1])
        full = int(np.argmax(per_bank))
        ax_pt = bx.get_position().height*fig.get_figheight()*72          # axes height in points
        lab_h = 9.0*ymax/ax_pt                                           # a 7 pt label with its box, in counts
        for b in range(T):
            h = int(per_bank[b])
            bx.bar(b, h, width=0.72, color=BANK[b], edgecolor=INK if b == full else 'none',
                   linewidth=1.0, zorder=2)
            weight = 'bold' if b == full else 'normal'
            if load/2 - lab_h - 2.3 < h < load/2 - 0.7:              # an outside label would cross the line
                bx.text(b, h - 1.2, str(h), ha='center', va='top', fontsize=7, color=LABEL_IN[b],
                        fontweight=weight, zorder=4)
            else:
                bx.text(b, h + 1.5, str(h), ha='center', va='bottom', fontsize=7, color=INK,
                        fontweight=weight, zorder=4, bbox=dict(boxstyle='square,pad=0.08', fc='white', ec='none'))
        bx.axhline(load/2, color=INK, lw=0.7, ls=(0, (3, 2)), zorder=3)
        bx.set_ylim(0, ymax)
        bx.set_xlim(-0.55, T - 0.45)
        bx.set_xticks(range(T))
        bx.set_yticks([load/2])
        bx.set_yticklabels([f'{load/2:g}'], color=MUTED)
        bx.tick_params(length=0, pad=1.5)
        if r < len(rows) - 1:
            bx.set_xticklabels([])
        else:
            bx.set_xlabel('bank', labelpad=1.5)
        for sp in ('top', 'right', 'left'):
            bx.spines[sp].set_visible(False)
        bx.text(T - 0.45, ymax*1.02, f'm = {m} \u2192 {cyc} cyc', fontsize=7, color=INK, ha='right', va='bottom')
    out = HERE/'fig1_layouts'
    fig.savefig(out.with_suffix('.png'), dpi=300)
    fig.savefig(out.with_suffix('.pdf'))
    print('wrote', out.with_suffix('.png'), out.with_suffix('.pdf'))


if __name__ == '__main__':
    main()
