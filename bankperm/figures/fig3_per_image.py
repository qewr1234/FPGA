"""Fig. 3: per-image W = 4 saving of the board network's layouts, against the perfect-balance bound.

    python bankperm/figures/fig3_per_image.py  # writes bankperm/figures/fig3_per_image.{png,pdf}

B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat), W = 4 count of conv1-conv10 (sparse
mode, fill and drain left out), sigma 25, test_noise seed 0, the 79 images of
Set12 + BSD68 other than Set12 01.png. Per image, 100 * (original - layout) /
original for:
  - perfect balance, m = ceil(nnz/4) in every window (bankperm/baselines.json
    per_image 'perfect_balance'): no assignment of a window's taps to the banks
    counts less;
  - the data-free skew, bank (p + s) % 4 (bankperm/skew_count.json,
    conventional against skewed 'w4');
  - Multi-start and Frozen, the two fitted relabelings run on the board
    (bankperm/b32_testsets.json, counts of the exported networks). Set12 02 and
    03 are in Multi-start's calibration set (Cal-3), Set12 01 (left out) is
    Frozen's.
Images are sorted by the bound's saving; Set12 05.png, the board image, is
marked. Before plotting, the original (conventional) totals of the three files
are checked to agree on every image, and each layout's pooled saving is
recomputed from the per-image counts and checked against its file's summary.
Drawn at 8.0 cm, the width the build places it at (build_docx --col-fig-cm 8), so
the 7 pt text is 7 pt in print.
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
CAL = ('Set12', '01.png')
BOARD = ('Set12', '05.png')


def setup_fonts():
    for f in ('Liberation Sans', 'Arial', 'DejaVu Sans'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'pdf.fonttype': 42, 'ps.fonttype': 42})


def load():
    """{(set, image): {'original', 'bound', 'skew', 'multistart', 'frozen'}} W = 4 counts, with the agreement check."""
    base = json.loads((BANKPERM/'baselines.json').read_text())
    skew = json.loads((BANKPERM/'skew_count.json').read_text())
    tests = json.loads((BANKPERM/'b32_testsets.json').read_text())
    model = 'dn_d10_c32_us_fx_qat'
    sk = skew['networks']['B-32 ReLU + QAT s1']
    assert base['model'] == sk['model'] == tests['model'] == skew['board_network']['model'] == model
    rows, bad = {}, []
    for r in tests['images']:
        key = (r['set'], r['image'])
        b = base['per_image'][f'{key[0]}/{key[1]}']
        s = sk['images'][f'{key[0]} {key[1]}']
        o = {r['w4']['original'], b['original'], s['conventional']['w4']}
        if len(o) != 1:
            bad.append((key, r['w4']['original'], b['original'], s['conventional']['w4']))
        if b['frozen_published'] != r['w4']['frozen'] or b['multistart_published'] != r['w4']['multistart']:
            bad.append((key, 'published layouts differ between baselines.json and b32_testsets.json'))
        rows[key] = dict(original=r['w4']['original'], bound=b['perfect_balance'], skew=s['skewed']['w4'],
                         multistart=r['w4']['multistart'], frozen=r['w4']['frozen'])
    assert len(rows) == 80 and set(f'{a}/{b}' for a, b in rows) == set(base['per_image']) \
        and set(f'{a} {b}' for a, b in rows) == set(sk['images'])
    print(f'check: original W = 4 totals of b32_testsets.json, baselines.json and skew_count.json '
          f'(conventional) agree on {80 - len([x for x in bad if len(x) == 4])}/80 images; '
          f'Frozen and Multi-start counts of baselines.json equal b32_testsets.json on '
          f'{80 - len([x for x in bad if len(x) == 2])}/80')
    if bad:
        for x in bad:
            print('  MISMATCH', x)
        raise SystemExit('data check failed')
    rows.pop(CAL)
    summaries = {'bound': base['summary']['79']['perfect_balance']['pooled_pct'],
                 'skew': skew['board_network']['saving_percent_79_images_other_than_01']['w4']['pooled'],
                 'multistart': tests['summaries']['79 without 01.png']['multistart']['w4']['pooled'],
                 'frozen': tests['summaries']['79 without 01.png']['frozen']['w4']['pooled']}
    return rows, summaries


def main():
    setup_fonts()
    rows, summaries = load()
    keys = list(rows)
    orig = np.array([rows[k]['original'] for k in keys], float)
    series = {}
    for name in ('bound', 'skew', 'multistart', 'frozen'):
        v = np.array([rows[k][name] for k in keys], float)
        pooled = 100*(orig.sum() - v.sum())/orig.sum()
        assert abs(pooled - summaries[name]) < 1e-3, (name, pooled, summaries[name])
        series[name] = (100*(orig - v)/orig, pooled)
    sav = {n: s for n, (s, _) in series.items()}
    order = np.argsort(sav['bound'], kind='stable')
    rank = np.arange(1, len(keys) + 1)
    board = [keys[i] for i in order].index(BOARD)            # 0-based position of 05.png in the sorted order
    for n, (s, pooled) in series.items():
        print(f'{n:<11} pooled {pooled:6.2f}%  per image {s.min():5.2f}..{s.max():5.2f}%  '
              f'median {np.median(s):5.2f}%  05.png {s[keys.index(BOARD)]:5.2f}%')
    out77 = np.array([k not in (('Set12', '02.png'), ('Set12', '03.png')) for k in keys])
    below = np.all([sav[n] <= sav['bound'] for n in ('skew', 'multistart', 'frozen')], axis=0)
    print(f'skew > Multi-start on {int((sav["skew"] > sav["multistart"]).sum())}/79 images '
          f'({int((sav["skew"] > sav["multistart"])[out77].sum())}/77 without Set12 02-03), '
          f'skew > Frozen on {int((sav["skew"] > sav["frozen"]).sum())}/79; '
          f'all three layouts at or below the bound on {int(below.sum())}/79')
    print(f'share of the perfect-balance saving, pooled: skew {100*series["skew"][1]/series["bound"][1]:.1f}%, '
          f'Multi-start {100*series["multistart"][1]/series["bound"][1]:.1f}%, '
          f'Frozen {100*series["frozen"][1]/series["bound"][1]:.1f}%')
    print(f'Set12 05.png: rank {board + 1} of 79 by the bound')

    fig, ax = plt.subplots(figsize=(8.0/2.54, 5.5/2.54), dpi=300)
    ax.vlines(board + 1, 4, 12.6, color=MUTED, lw=0.6, ls=(0, (1, 1.5)), zorder=1)   # stops below the legend
    ax.annotate('Set12 05.png (board)', (board + 1, 4.55), xytext=(2.5, 0), textcoords='offset points', ha='left',
                va='center', fontsize=7, color=MUTED)
    ax.plot(rank, sav['bound'][order], color=INK, lw=1.0, zorder=3)
    style = {'skew': dict(marker='^', ms=2.9, mfc=AQUA, mec=AQUA, mew=0.5),
             'multistart': dict(marker='o', ms=2.7, mfc='white', mec=BLUE, mew=0.7),
             'frozen': dict(marker='s', ms=2.3, mfc=ORANGE, mec=ORANGE, mew=0.4)}
    for n, st in style.items():
        ax.plot(rank, sav[n][order], ls='', zorder=4 if n == 'skew' else 3, **st)
    ax.set_xlim(0, 80)
    ax.set_xticks([1, 20, 40, 60, 79])
    ax.set_ylim(4, 17.2)
    ax.set_yticks([4, 8, 12, 16])
    ax.set_xlabel('image, by perfect-balance saving', labelpad=1.5)
    ax.set_ylabel('saving at W = 4 (%)', labelpad=2)
    ax.tick_params(length=2, pad=1.5)
    ax.grid(True, axis='y', color=GRID, lw=0.5, zorder=0)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    lab = {'bound': 'perfect balance', 'skew': 'skew', 'multistart': 'Multi-start', 'frozen': 'Frozen'}
    handles = [Line2D([], [], color=INK, lw=1.0, label=f'{lab["bound"]} ({series["bound"][1]:.2f})')]
    handles += [Line2D([], [], ls='', label=f'{lab[n]} ({series[n][1]:.2f})', **dict(st, ms=st['ms'] + 0.8))
                for n, st in style.items()]
    leg = ax.legend(handles=handles, loc='upper left', frameon=False, handlelength=1.3, handletextpad=0.4,
                    borderaxespad=0.2, labelspacing=0.25, title='pooled saving (%)', title_fontsize=7,
                    alignment='left')
    leg.get_title().set_color(MUTED)
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout(pad=0.25)
    out = HERE/'fig3_per_image'
    fig.savefig(out.with_suffix('.png'), dpi=300)
    fig.savefig(out.with_suffix('.pdf'))
    print('wrote', out.with_suffix('.png'), out.with_suffix('.pdf'))


if __name__ == '__main__':
    main()
