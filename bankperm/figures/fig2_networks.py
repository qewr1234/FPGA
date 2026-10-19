"""Fig. 2: the ten-network study (PROTOCOL_2), saving of the three layouts at W = 4 and W = 2.

    python bankperm/figures/fig2_networks.py   # writes bankperm/figures/fig2_networks.{png,pdf}

Per network (bankperm/results_2.json, 4a93e08): the pooled saving over the 79
images other than Set12 01.png (the calibration image of L1 and L3), count of
conv1-convL, 100 * (L0 - layout) / L0 on the summed counts, for
  - L1 relabeling (perms.json, the PROTOCOL.md recipe; on R1 the board's Frozen),
  - L2 skew, bank (s + p) % 4 (data-free),
  - L3 skew + relabeling (perms_2.json, the same recipe fitted under the skewed rule),
with the paired bootstrap 95% interval of results_2.json drawn as an error bar
behind the marker: at this scale every interval is narrower than its marker
(the script prints the largest half-width), which the caption should say.
Top panel W = 4, bottom panel W = 2 (smaller).
Where bankperm/bounds.json says no layout can pay (condition (2) holds in every
layer: W = 2 on A and R1-R3), one x at 0 stands for all three layouts, after
checking that L1, L2 and L3 count exactly as L0 on all 80 images there (H4).
W = 1 is zero by shape on every network; checked the same way, stated in a note.
On 10 x 45 (C = 45, C % 4 = 1) the conventional layout already has the skew's
banks: L2 = L0 and L3 = L1 by construction (checked on every image), drawn as
the skew at exactly 0 with the label 'conv. = skew'.
Pooled values are recomputed from per_image_totals and checked against
summary_79; the bootstrap intervals are recomputed with the protocol's
generator (np.random.default_rng(0).integers(0, 79, (10000, 79)), one draw for
every network, width and layout, 79 images in sorted order) and checked.
Short labels (printed): A, B, R1-R3, M1-M3, Av2, 45.
Drawn at 8.0 cm, the width the build places it at (build_docx --col-fig-cm 8), so
the 7 pt text is 7 pt in print. Colours and markers match Fig. 3 (relabeling =
Frozen's orange square, skew aqua triangle, skew + relabeling dark gray diamond);
the shapes keep the layouts apart in a grayscale print.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.lines import Line2D

HERE = Path(__file__).resolve().parent
BANKPERM = HERE.parent

BLUE, ORANGE, AQUA, INK, MUTED = '#2a78d6', '#eb6834', '#1baf7a', '#0b0b0b', '#52514e'
GRID = '#e6e5e1'
SHORT = {  # results_2.json label -> (short label, definition, x position: families set apart)
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
IDX = {'L0': 0, 'L1': 1, 'L2': 2, 'L3': 3}           # results_2.json layout_order_in_lists
LAYOUTS = ('L1', 'L2', 'L3')
DX = {'L1': -0.27, 'L2': 0.0, 'L3': 0.27}
NAME = {'L1': 'relabeling', 'L2': 'skew', 'L3': 'skew + relabeling'}
DARK = '#3d3c39'                                       # skew + relabeling: darker than MUTED, still not INK
STYLE = {'L1': dict(marker='s', mfc=ORANGE, mec=ORANGE, color=ORANGE),
         'L2': dict(marker='^', mfc=AQUA, mec=AQUA, color=AQUA),
         'L3': dict(marker='D', mfc=DARK, mec=DARK, color=DARK)}
MS = {'w4': {'L1': 3.3, 'L2': 3.9, 'L3': 3.2}, 'w2': {'L1': 2.6, 'L2': 3.1, 'L3': 2.5}}


def setup_fonts():
    for f in ('Liberation Sans', 'Arial', 'DejaVu Sans'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'pdf.fonttype': 42, 'ps.fonttype': 42})


def pooled(l0, lx):
    return 100*(l0.sum(axis=-1) - lx.sum(axis=-1))/l0.sum(axis=-1)


def network_stats(label, net, boot_idx):
    """{w: {layout: (pooled %, lo, hi, equal to L0 on all 80 images)}}, every value checked against results_2.json."""
    tot = net['per_image_totals']
    assert len(tot) == 80 and CAL in tot
    keys = sorted(k for k in tot if k != CAL)               # the 79, in the bootstrap's sorted order
    assert len(keys) == 79
    out = {}
    for w in ('w1', 'w2', 'w4'):
        arr80 = np.array([tot[k][w][:4] for k in sorted(tot)], dtype=np.int64)      # 80 x [L0, L1, L2, L3]
        arr = np.array([tot[k][w][:4] for k in keys], dtype=np.int64)                # 79 x 4
        l0 = arr[:, 0].astype(float)
        out[w] = {}
        for lay in LAYOUTS:
            lx = arr[:, IDX[lay]].astype(float)
            p = float(pooled(l0, lx))
            s = net['summary_79'][w][lay]
            assert abs(p - s['pooled_pct']) < 1e-9, (label, w, lay, p, s['pooled_pct'])
            assert int(l0.sum()) == s['L0_cycles'] and int(lx.sum()) == s['layout_cycles'], (label, w, lay)
            bs = pooled(l0[boot_idx], lx[boot_idx])
            lo, hi = np.percentile(bs, [2.5, 97.5])
            assert abs(lo - s['bootstrap_95_pct'][0]) < 1e-9 and abs(hi - s['bootstrap_95_pct'][1]) < 1e-9, \
                (label, w, lay, lo, hi, s['bootstrap_95_pct'])
            out[w][lay] = (p, lo, hi, bool(np.all(arr80[:, IDX[lay]] == arr80[:, 0])))
        if net['C_mod_4_is_0'] is False:                     # 10 x 45: L2 = L0 and L3 = L1 by construction
            assert np.all(arr80[:, 2] == arr80[:, 0]) and np.all(arr80[:, 3] == arr80[:, 1]), (label, w)
    return out


def main():
    setup_fonts()
    r2 = json.loads((BANKPERM/'results_2.json').read_text())
    res = r2['networks']
    bounds = json.loads((BANKPERM/'bounds.json').read_text())['networks']
    assert list(res) == list(SHORT) and set(bounds) == set(SHORT)
    assert r2['layout_order_in_lists'].startswith('per_image_totals[image][wN] = [L0, L1, L2, L3]')
    assert all(r2['cross_checks'].values()) and all(v['holds'] for v in r2['verdicts'].values())
    assert r2['bootstrap']['resamples'] == 10000
    boot_idx = np.random.default_rng(0).integers(0, 79, (10000, 79))     # as results_2.json 'bootstrap'

    height_cm = 5.0                                   # the paper is at its 4-page limit (5.3 before the board results)
    fig = plt.figure(figsize=(8.0/2.54, height_cm/2.54), dpi=300)
    gs = fig.add_gridspec(2, 1, height_ratios=(2.2, 1.0), hspace=0.17, left=0.105, right=0.995,
                          top=1 - 0.50/height_cm, bottom=0.44/height_cm)
    ax4 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax4)
    axes = {'w4': ax4, 'w2': ax2}
    print('labels:')
    by_shape, rows = [], []
    for label, (short, definition, x) in SHORT.items():
        net = res[label]
        assert bounds[label]['model'] == net['model'] and bounds[label]['can_pay'] == net['can_pay']
        print(f'  {short:<4} {definition}  ({label}, {net["model"]}, C = {net["C_in_of_fitted_layers"]})')
        st = network_stats(label, net, boot_idx)
        assert not bounds[label]['can_pay']['w1'] and all(st['w1'][l][3] and st['w1'][l][0] == 0 for l in LAYOUTS)
        for w, ax in axes.items():
            if not bounds[label]['can_pay'][w]:
                assert all(st[w][l][3] and st[w][l][0] == 0 for l in LAYOUTS), (label, w)   # H4: exactly L0
                ax.plot(x, 0, marker='x', ms=3.6 if w == 'w2' else 4.2, mew=1.0, color=INK, ls='', zorder=4,
                        clip_on=False)
                by_shape.append(f'{short} {w}')
                continue
            for lay in LAYOUTS:
                p, lo, hi, eq = st[w][lay]
                xx = x + DX[lay]
                ax.plot([xx, xx], [lo, hi], color=STYLE[lay]['color'], lw=0.7, solid_capstyle='butt', zorder=2)
                ax.plot(xx, p, ls='', ms=MS[w][lay], mew=0.5, zorder=3, clip_on=False,
                        **{k: v for k, v in STYLE[lay].items() if k != 'color'})
        line = f'  {short:<4}'
        for w in ('w4', 'w2'):
            if bounds[label]['can_pay'][w]:
                d = st[w]['L3'][0] - st[w]['L2'][0]
                line += (f'  {w}: ' + '  '.join(f'{l} {st[w][l][0]:6.3f} [{st[w][l][1]:6.3f}, {st[w][l][2]:6.3f}]'
                                                for l in LAYOUTS) + f'  L3-L2 {d:+.3f}')
            else:
                line += f'  {w}: 0 by shape (all layouts = L0 on 80 images)'
        rows.append(line)
    print('pooled saving (%) over the 79 images [bootstrap 95%]:')
    print('\n'.join(rows))
    for w in ('w4', 'w2'):
        hw = max(((hi - lo)/2, SHORT[lab][0], l) for lab in SHORT for l in LAYOUTS
                 for (p, lo, hi, eq) in [network_stats(lab, res[lab], boot_idx)[w][l]])
        print(f'largest bootstrap half-width at {w}: {hw[0]:.3f} points ({hw[1]} {hw[2]})')
    print('zero by shape (bounds.json; L1, L2, L3 exactly = L0 on all 80 images):', ', '.join(by_shape))
    print('W = 1: zero by shape on all ten networks, L1-L3 exactly = L0 on every image (checked)')

    # 10 x 45: the skew is the conventional layout there
    x45 = SHORT['10 x 45 ReLU + QAT'][2]
    ax4.annotate('conv. =\nskew', (x45 + DX['L2'], 0.35), xytext=(x45 - 0.22, 3.3), textcoords='data',
                 ha='center', va='bottom', fontsize=7, color=INK, linespacing=1.05,
                 arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.5, shrinkA=0.5, shrinkB=2.2))
    st45 = network_stats('10 x 45 ReLU + QAT', res['10 x 45 ReLU + QAT'], boot_idx)
    ax2.annotate(f'{st45["w2"]["L1"][0]:.2f}', (x45 + DX['L1'], st45['w2']['L1'][0]), xytext=(-3.2, 0),
                 textcoords='offset points', ha='right', va='center', fontsize=7, color=INK)

    for w, ax in axes.items():
        ax.grid(True, axis='y', color=GRID, lw=0.5, zorder=0)
        ax.tick_params(length=2, pad=1.5)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        ax.text(1.0, 1.0, 'W = 4' if w == 'w4' else 'W = 2', transform=ax.transAxes, ha='right', va='top',
                fontsize=7, color=INK, fontweight='bold')
    ax4.set_ylim(-0.6, 14.4)
    ax4.set_yticks([0, 5, 10])
    ax2.set_ylim(-0.6, 10.6)
    ax2.set_yticks([0, 5, 10])
    ax2.set_xticks([v[2] for v in SHORT.values()])
    ax2.set_xticklabels([v[0] for v in SHORT.values()])
    ax2.set_xlim(-0.5, 10.65)
    plt.setp(ax4.get_xticklabels(), visible=False)
    ax4.tick_params(axis='x', length=0)
    ax2.text(SHORT['B-32 ReLU + QAT s2'][2], 1.9, '×: 0 by shape,\nevery layout', ha='center',
             va='bottom', fontsize=7, color=MUTED, linespacing=1.1)
    ax4.text(6.55, 14.4, 'W = 1: 0 on every\nnetwork (by shape)', ha='center', va='top', fontsize=7, color=MUTED,
             linespacing=1.1)
    fig.text(0.012, (gs[0].get_position(fig).y1 + gs[1].get_position(fig).y0)/2, 'saving vs. original (%)',
             rotation=90, ha='left', va='center', fontsize=7, color=INK)

    handles = [Line2D([], [], ls='', ms=MS['w4'][l] + 0.3, mew=0.5, label=NAME[l],
                      **{k: v for k, v in STYLE[l].items() if k != 'color'}) for l in LAYOUTS]
    leg = fig.legend(handles=handles, loc='upper center', ncol=3, frameon=False, handlelength=1.0,
                     handletextpad=0.35, columnspacing=1.3, borderaxespad=0.1, bbox_to_anchor=(0.55, 1.0))
    for t in leg.get_texts():
        t.set_color(INK)
    out = HERE/'fig2_networks'
    fig.savefig(out.with_suffix('.png'), dpi=300)
    fig.savefig(out.with_suffix('.pdf'))
    print('wrote', out.with_suffix('.png'), out.with_suffix('.pdf'))


if __name__ == '__main__':
    main()
