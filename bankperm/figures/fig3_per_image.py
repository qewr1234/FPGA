"""Fig. 3: per-image W = 4 saving of the board network's layouts, against the perfect-balance bound.

    python bankperm/figures/fig3_per_image.py  # writes bankperm/figures/fig3_per_image.{png,pdf}

B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat), W = 4 count of conv1-conv10 (sparse
mode, fill and drain left out), sigma 25, test_noise seed 0, the 79 images of
Set12 + BSD68 other than Set12 01.png. Per image, 100 * (original - layout) /
original for:
  - perfect balance, m = ceil(nnz/4) in every window (bankperm/baselines.json
    per_image 'perfect_balance'): no assignment of a window's taps to the banks
    counts less;
  - skew + relabeling, PROTOCOL_2's L3 (bankperm/results_2.json per_image_totals,
    entry 3: perms_2.json's classes fitted under the skewed rule on Set12 01.png);
  - the data-free skew, bank (p + s) % 4 (bankperm/skew_count.json,
    conventional against skewed 'w4');
  - Multi-start and Frozen, the two fitted relabelings run on the board
    (bankperm/b32_testsets.json, counts of the exported networks). Set12 02 and
    03 are in Multi-start's calibration set (Cal-3), Set12 01 (left out) is
    Frozen's and L3's.
Images are sorted by the bound's saving; Set12 05.png, the board image, is
marked. Before plotting: the original (conventional) totals of b32_testsets.json,
baselines.json, skew_count.json and results_2.json (L0) agree on every image;
results_2.json's L1, L2 and L1_multistart equal Frozen (b32_testsets.json and
baselines.json), the skew (skew_count.json) and Multi-start on every image; and
each layout's pooled saving, recomputed from the per-image counts, equals its
file's summary. Drawn at 8.0 cm, the width the build places it at (build_docx
--col-fig-cm 8), so the 7 pt text is 7 pt in print. Colours and markers match
Fig. 2; the shapes keep the five series apart in a grayscale print.
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
DARK = '#3d3c39'                     # skew + relabeling, as in Fig. 2
GRID = '#e6e5e1'
CAL = ('Set12', '01.png')
BOARD = ('Set12', '05.png')
NEXT_BOARD = (('Set12', '06.png'), ('Set12', '07.png'), ('Set12', '08.png'))   # PROTOCOL_2 board images
NETWORK = 'B-32 ReLU + QAT s1'


def setup_fonts():
    for f in ('Liberation Sans', 'Arial', 'DejaVu Sans'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 7, 'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'pdf.fonttype': 42, 'ps.fonttype': 42})


def load():
    """{(set, image): {'original', 'bound', 'combo', 'skew', 'multistart', 'frozen'}} W = 4 counts, checked."""
    base = json.loads((BANKPERM/'baselines.json').read_text())
    skew = json.loads((BANKPERM/'skew_count.json').read_text())
    tests = json.loads((BANKPERM/'b32_testsets.json').read_text())
    r2 = json.loads((BANKPERM/'results_2.json').read_text())
    model = 'dn_d10_c32_us_fx_qat'
    sk = skew['networks'][NETWORK]
    net2 = r2['networks'][NETWORK]
    assert base['model'] == sk['model'] == tests['model'] == skew['board_network']['model'] == net2['model'] == model
    assert net2['layouts'] == ['L0', 'L1', 'L2', 'L3', 'L1_multistart']
    assert r2['layout_order_in_lists'].startswith('per_image_totals[image][wN] = [L0, L1, L2, L3] (+ L1_multistart')
    rows, bad = {}, []
    for r in tests['images']:
        key = (r['set'], r['image'])
        b = base['per_image'][f'{key[0]}/{key[1]}']
        s = sk['images'][f'{key[0]} {key[1]}']
        l0, l1, l2, l3, l1ms = net2['per_image_totals'][f'{key[0]}/{key[1]}']['w4']
        o = {r['w4']['original'], b['original'], s['conventional']['w4'], l0}
        if len(o) != 1:
            bad.append((key, 'original', r['w4']['original'], b['original'], s['conventional']['w4'], l0))
        if b['frozen_published'] != r['w4']['frozen'] or b['multistart_published'] != r['w4']['multistart']:
            bad.append((key, 'published layouts differ between baselines.json and b32_testsets.json'))
        if (l1, l2, l1ms) != (r['w4']['frozen'], s['skewed']['w4'], r['w4']['multistart']):
            bad.append((key, 'results_2.json L1 / L2 / L1_multistart differ from Frozen / skew / Multi-start'))
        rows[key] = dict(original=r['w4']['original'], bound=b['perfect_balance'], combo=l3, skew=s['skewed']['w4'],
                         multistart=r['w4']['multistart'], frozen=r['w4']['frozen'])
    assert len(rows) == 80 and set(f'{a}/{b}' for a, b in rows) == set(base['per_image']) \
        and set(f'{a} {b}' for a, b in rows) == set(sk['images']) \
        and set(f'{a}/{b}' for a, b in rows) == set(net2['per_image_totals'])
    n_bad = {t: len([x for x in bad if x[1] == t]) for t in ('original',)}
    print(f'check: original W = 4 totals of b32_testsets.json, baselines.json, skew_count.json (conventional) '
          f'and results_2.json (L0) agree on {80 - n_bad["original"]}/80 images; Frozen and Multi-start of '
          f'baselines.json equal b32_testsets.json, and results_2.json L1 / L2 / L1_multistart equal Frozen / '
          f'skew / Multi-start, on {80 - len(bad) + n_bad["original"]}/80')
    if bad:
        for x in bad:
            print('  MISMATCH', x)
        raise SystemExit('data check failed')
    rows.pop(CAL)
    s79 = net2['summary_79']['w4']
    summaries = {'bound': (base['summary']['79']['perfect_balance']['pooled_pct'], 1e-3),
                 'combo': (s79['L3']['pooled_pct'], 1e-9),
                 'skew': (skew['board_network']['saving_percent_79_images_other_than_01']['w4']['pooled'], 1e-9),
                 'multistart': (tests['summaries']['79 without 01.png']['multistart']['w4']['pooled'], 1e-3),
                 'frozen': (tests['summaries']['79 without 01.png']['frozen']['w4']['pooled'], 1e-3)}
    cross = {'skew': s79['L2']['pooled_pct'], 'multistart': s79['L1_multistart']['pooled_pct'],
             'frozen': s79['L1']['pooled_pct']}
    intervals = {'combo': s79['L3']['bootstrap_95_pct'], 'skew': s79['L2']['bootstrap_95_pct'],
                 'multistart': s79['L1_multistart']['bootstrap_95_pct'], 'frozen': s79['L1']['bootstrap_95_pct']}
    st2 = json.loads((BANKPERM/'stats_2.json').read_text())
    assert st2['model'] == model and st2['checks']['all_ok']
    lay79 = st2['sets']['79']['layouts']
    intervals['bound'] = lay79['perfect_balance']['ci95_pct']
    for n, k in (('frozen', 'frozen'), ('multistart', 'multistart'), ('skew', 'skew')):   # the two files agree
        assert all(abs(a - b) < 1e-3 for a, b in zip(intervals[n], lay79[k]['ci95_pct'])), (n, intervals[n])
    return rows, summaries, cross, intervals


def main():
    setup_fonts()
    rows, summaries, cross, intervals = load()
    keys = list(rows)
    orig = np.array([rows[k]['original'] for k in keys], float)
    series = {}
    for name in ('bound', 'combo', 'skew', 'multistart', 'frozen'):
        v = np.array([rows[k][name] for k in keys], float)
        pooled = 100*(orig.sum() - v.sum())/orig.sum()
        ref, tol = summaries[name]
        assert abs(pooled - ref) < tol, (name, pooled, ref)
        if name in cross:
            assert abs(pooled - cross[name]) < 1e-9, (name, pooled, cross[name])
        series[name] = (100*(orig - v)/orig, pooled)
    sav = {n: s for n, (s, _) in series.items()}
    order = np.argsort(sav['bound'], kind='stable')
    rank = np.arange(1, len(keys) + 1)
    sorted_keys = [keys[i] for i in order]
    board = sorted_keys.index(BOARD)                          # 0-based position of 05.png in the sorted order
    for n, (s, pooled) in series.items():
        lo, hi = intervals[n]
        print(f'{n:<11} pooled {pooled:6.2f}% [{lo:5.2f}, {hi:5.2f}]  per image {s.min():5.2f}..{s.max():5.2f}%  '
              f'median {np.median(s):5.2f}%  05.png {s[keys.index(BOARD)]:5.2f}%  '
              f'share of bound {100*pooled/series["bound"][1]:5.1f}%')
    out77 = np.array([k not in (('Set12', '02.png'), ('Set12', '03.png')) for k in keys])
    below = np.all([sav[n] <= sav['bound'] for n in ('combo', 'skew', 'multistart', 'frozen')], axis=0)
    gt = lambda a, b: int((sav[a] > sav[b]).sum())                       # noqa: E731
    print(f'skew + relabeling > skew on {gt("combo", "skew")}/79 images, > Multi-start on '
          f'{gt("combo", "multistart")}/79, > Frozen on {gt("combo", "frozen")}/79; '
          f'per image L3 - L2 {np.min(sav["combo"] - sav["skew"]):.2f}..{np.max(sav["combo"] - sav["skew"]):.2f} points')
    print(f'skew > Multi-start on {gt("skew", "multistart")}/79 images '
          f'({int((sav["skew"] > sav["multistart"])[out77].sum())}/77 without Set12 02-03), '
          f'skew > Frozen on {gt("skew", "frozen")}/79; '
          f'all four layouts at or below the bound on {int(below.sum())}/79')
    m77 = {n: 100*(orig[out77].sum() - np.array([rows[k][n] for k in keys], float)[out77].sum())/orig[out77].sum()
           for n in ('combo', 'skew', 'multistart', 'frozen')}
    print('pooled on the 77 without Set12 02-03: ' + ', '.join(f'{n} {v:.2f}%' for n, v in m77.items()))
    print(f'Set12 05.png: rank {board + 1} of 79 by the bound; '
          + ', '.join(f'{k[1]}: rank {sorted_keys.index(k) + 1}' for k in NEXT_BOARD))

    fig, ax = plt.subplots(figsize=(8.0/2.54, 5.5/2.54), dpi=300)   # as before: 4-page limit
    ax.vlines(board + 1, 4, 11.1, color=MUTED, lw=0.6, ls=(0, (1, 1.5)), zorder=1)   # stops below the bound
    ax.annotate('Set12 05.png (board)', (board + 1, 4.55), xytext=(2.5, 0), textcoords='offset points', ha='left',
                va='center', fontsize=7, color=MUTED)
    ax.plot(rank, sav['bound'][order], color=INK, lw=1.0, zorder=3)
    style = {'combo': dict(marker='D', ms=2.3, mfc=DARK, mec=DARK, mew=0.4),
             'skew': dict(marker='^', ms=2.9, mfc=AQUA, mec=AQUA, mew=0.5),
             'multistart': dict(marker='o', ms=2.7, mfc='white', mec=BLUE, mew=0.7),
             'frozen': dict(marker='s', ms=2.3, mfc=ORANGE, mec=ORANGE, mew=0.4)}
    for n, st in style.items():
        ax.plot(rank, sav[n][order], ls='', zorder=4 if n in ('combo', 'skew') else 3, **st)
    ax.set_xlim(0, 80)
    ax.set_xticks([1, 20, 40, 60, 79])
    ax.set_ylim(4, 17.9)
    ax.set_yticks([4, 8, 12, 16])
    ax.set_xlabel('image, by perfect-balance saving', labelpad=1.5)
    ax.set_ylabel('saving at W = 4 (%)', labelpad=2)
    ax.tick_params(length=2, pad=1.5)
    ax.grid(True, axis='y', color=GRID, lw=0.5, zorder=0)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    lab = {'bound': 'perfect balance', 'combo': 'skew + relabeling', 'skew': 'skew', 'multistart': 'Multi-start',
           'frozen': 'Frozen'}
    handles = [Line2D([], [], color=INK, lw=1.0, label=f'{lab["bound"]} ({series["bound"][1]:.2f})')]
    handles += [Line2D([], [], ls='', label=f'{lab[n]} ({series[n][1]:.2f})', **dict(st, ms=st['ms'] + 0.8))
                for n, st in style.items()]
    leg = ax.legend(handles=handles, loc='upper left', frameon=False, handlelength=1.3, handletextpad=0.4,
                    borderaxespad=0.2, labelspacing=0.2, title='pooled saving (%)', title_fontsize=7,
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
