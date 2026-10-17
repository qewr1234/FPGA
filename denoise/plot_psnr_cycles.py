"""PSNR against core cycles per pixel for every exported denoiser (the paper's iso-cycle figure).

    python denoise/plot_psnr_cycles.py          # writes denoise/figures/psnr_vs_cycles.{pdf,png}
    python denoise/plot_psnr_cycles.py --en     # English labels: psnr_vs_cycles_en.{pdf,png}

Points are the integer (board-arithmetic) Set12 PSNRs from denoise/export/*/int_eval.json
at the corrected cycle model's cost (board-measured models marked); the B-32 points are
the fixed-budget (120 epochs + 15 QAT epochs) networks, three seeds each, joined by their
range and drawn 5% apart in x (both cost about 670 cycles), with the parameter-matched
45-channel ReLU network beside them, BM3D under the paper's input and on unclipped noise
as horizontal lines, and the public DnCNN-S on the same input at its modelled cost.
Second panel: BSD68.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from results_table import model_cycles, board_cycles  # noqa: E402

# the three validated categorical slots (all-pairs safe), plus neutral ink for references
BLUE, ORANGE, AQUA, INK, MUTED = '#2a78d6', '#eb6834', '#1baf7a', '#0b0b0b', '#52514e'

MODELS = [  # name or seed group, label, family, marker, x factor (B-32 groups drawn apart)
    ('dn_d7_c32_es', 'A: 7층×32', 'A', 'o', 1.0),
    ('dn_d10_c64_us_es', 'B', 'B', 's', 1.0),
    ('dn_d10_c64_us_es_qat', 'B+QAT', 'B', 's', 1.0),
    (('dn_d10_c32_us_fx_qat', 'dn_d10_c32_us_fx_s2_qat', 'dn_d10_c32_us_fx_s3_qat'), 'B-32 ReLU+QAT', 'R', '^', 1/1.05),
    (('dn_d10_c32_us_mo_fx_qat', 'dn_d10_c32_us_mo_fx_s2_qat', 'dn_d10_c32_us_mo_fx_s3_qat'), 'B-32 maxout+QAT', 'M', 'D', 1.05),
    ('dn_d10_c45_us_fx_qat', '45ch ReLU+QAT', 'R', 'v', 1.0),
]
COLOR = {'A': INK, 'B': BLUE, 'R': AQUA, 'M': ORANGE}
LABEL_DX = {  # per-panel label offsets (points) by label, chosen by looking at the render; None = no label
    # (dx, dy, anchor): the label hangs off the group's lowest ('lo') or highest ('hi') point
    'Set12': {'A: 7층×32': (6, -3, 'lo'), 'B': None, 'B+QAT': (6, 2, 'hi'), 'B-32 ReLU+QAT': (6, -1, 'lo'),
              'B-32 maxout+QAT': (8, 7, 'hi'), '45ch ReLU+QAT': (5, -5, 'lo')},
    'BSD68': {'A: 7층×32': (6, -3, 'lo'), 'B': None, 'B+QAT': (6, 2, 'hi'), 'B-32 ReLU+QAT': (6, -1, 'lo'),
              'B-32 maxout+QAT': (8, 7, 'hi'), '45ch ReLU+QAT': (5, -5, 'lo')},
}
LABEL_TEXT = {'B+QAT': 'B, B+QAT'}  # the two B points sit on top of each other


TEXT = {
    'ko': dict(dncnn='DnCNN-S\n(float, 같은 입력)', bm_clip='BM3D, 클리핑 7비트 입력', bm_raw='BM3D, 클리핑 없음',
               xlabel='코어 사이클 / 픽셀 (로그)', ylabel='{} PSNR (dB), 정수', a='A: 7층×32',
               relu3='B-32 ReLU+QAT (시드 3개)', mo3='B-32 maxout+QAT\n(시드 3개)', c45='45채널 ReLU+QAT',
               leg=['space-to-depth, 10층×64', '10층×32, maxout', '10층×32·45, ReLU', '7층×32 (기준)', '속 빈 점 = 사이클 모델값'],
               suffix=''),
    'en': dict(dncnn='DnCNN-S\n(float, same input)', bm_clip='BM3D, clipped 7-bit input', bm_raw='BM3D, unclipped',
               xlabel='core cycles / pixel (log)', ylabel='{} PSNR (dB), integer', a='A: 7×32',
               relu3='B-32 ReLU+QAT (3 seeds)', mo3='B-32 maxout+QAT\n(3 seeds)', c45='45-ch ReLU+QAT',
               leg=['space-to-depth, 10×64', '10×32, maxout', '10×32 and 10×45, ReLU', '7×32 (baseline)', 'hollow = cycle model'],
               suffix='_en'),
}


def main():
    lang = 'en' if '--en' in sys.argv else 'ko'
    T = TEXT[lang]
    for f in ('NanumGothic', 'NanumBarunGothic', 'Malgun Gothic'):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams.update({'font.size': 8, 'axes.titlesize': 8, 'axes.labelsize': 8, 'legend.fontsize': 7,
                         'xtick.labelsize': 7, 'ytick.labelsize': 7, 'axes.edgecolor': MUTED, 'axes.linewidth': 0.6})
    bm = json.loads((HERE/'baselines.json').read_text())['sets']
    bmp = json.loads((HERE/'bm3d_protocol.json').read_text())['sets']
    dn = json.loads((HERE/'dncnn_s_protocol.json').read_text())['sets']
    dn_cycles = 9296  # cycle model for 17 x 64 x 3x3 on this core (denoise/results_table.py conventions)

    fig, axes = plt.subplots(1, 2, figsize=(6.9, 2.35), dpi=200)
    for ax, s in zip(axes, ('Set12', 'BSD68')):
        text = {'A: 7층×32': T['a'], 'B-32 ReLU+QAT': T['relu3'], 'B-32 maxout+QAT': T['mo3'], '45ch ReLU+QAT': T['c45']}
        for names, label, fam, mk, fx in MODELS:
            names = (names,) if isinstance(names, str) else names
            pts = []
            for name in names:
                man = json.loads((HERE/'export'/name/'manifest.json').read_text())
                ev = json.loads((HERE/'export'/name/'int_eval.json').read_text())
                x = (board_cycles(name) or model_cycles(man))*fx
                y = ev[s]['integer']
                filled = board_cycles(name) is not None
                ax.plot(x, y, mk, ms=5.5 if len(names) == 1 else 4.5, mfc=COLOR[fam] if filled else 'white',
                        mec=COLOR[fam], mew=1.2, zorder=3.5 if filled else 3)   # a board point stays visible
                pts.append((x, y))
            if len(pts) > 1:                           # the seeds' range
                ax.plot([pts[0][0]]*2, [min(p[1] for p in pts), max(p[1] for p in pts)], color=COLOR[fam], lw=0.8, zorder=2)
            if LABEL_DX[s][label] is not None:
                dx, dy, at = LABEL_DX[s][label]
                x, y = pts[0][0], (max if at == 'hi' else min)(p[1] for p in pts)
                ax.annotate(LABEL_TEXT.get(label, text.get(label, label)), (x, y), xytext=(dx, dy), textcoords='offset points',
                            fontsize=6.5, color=INK, zorder=4, ha='center' if at == 'hi' and dy > 2 else ('right' if dx < 0 else 'left'),
                            va='bottom' if dy > 2 else ('top' if dy < -2 else 'center'))
        ax.plot(dn_cycles, dn[s]['clip7']['mean'], 'o', ms=5.5, mfc='white', mec=MUTED, mew=1.2, zorder=3)
        ax.annotate(T['dncnn'], (dn_cycles, dn[s]['clip7']['mean']), xytext=(-6, 2),
                    textcoords='offset points', fontsize=6.5, color=INK, ha='right')
        for y, txt, ls, dy in ((bm[s]['bm3d']['mean'], T['bm_clip'], '-', -8),
                               (bmp[s]['raw_sigma25']['mean'], T['bm_raw'], '--', 2)):
            ax.axhline(y, color=MUTED, lw=0.8, ls=ls, zorder=1)
            ax.annotate(txt, (13500, y), xytext=(0, dy), textcoords='offset points', fontsize=6.5, color=MUTED, ha='right')
        ax.set_xscale('log')
        ax.set_xlim(480, 14000)
        ax.set_xticks([500, 1000, 2000, 5000, 10000])
        ax.set_xticklabels(['500', '1k', '2k', '5k', '10k'])
        ax.set_xlabel(T['xlabel'])
        ax.set_ylabel(T['ylabel'].format(s))
        ax.grid(True, which='major', color='#e6e5e1', lw=0.5, zorder=0)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylim(28.9, 30.6)
    axes[1].set_ylim(28.1, 29.4)
    # legend by family (identity is also in the direct labels; filled = board-measured cost)
    from matplotlib.lines import Line2D
    lg = T['leg']
    handles = [Line2D([], [], marker='s', color=BLUE, ls='', ms=5, label=lg[0]),
               Line2D([], [], marker='D', color=ORANGE, ls='', ms=5, label=lg[1]),
               Line2D([], [], marker='^', color=AQUA, ls='', ms=5, label=lg[2]),
               Line2D([], [], marker='o', color=INK, ls='', ms=5, label=lg[3]),
               Line2D([], [], marker='o', color=MUTED, mfc='white', ls='', ms=5, label=lg[4])]
    fig.legend(handles=handles, loc='lower center', ncol=5, frameon=False, handletextpad=0.3, columnspacing=1.2,
               bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(w_pad=1.5, rect=(0, 0.07, 1, 1))
    out = HERE/'figures'/('psnr_vs_cycles' + T['suffix'])
    fig.savefig(out.with_suffix('.pdf')); fig.savefig(out.with_suffix('.png'))
    print('wrote', out.with_suffix('.pdf'), out.with_suffix('.png'))


if __name__ == '__main__':
    main()
