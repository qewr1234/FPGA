"""Figures for the proposal.

    python proposal/make_figures.py

  fig_system.png        block diagram of what runs where
  fig_board_compare.png the board comparison figure (denoise/figures/
                        05_dn_d7_c32_board.pdf, made on the lab PC from a real
                        board run), rasterized so the HTML/PDF can embed it

Needs matplotlib, and pymupdf for the rasterization. Korean labels use the
first of NanumGothic / Malgun Gothic / AppleGothic that is installed.
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE/'figures'

for name in ('NanumGothic', 'Malgun Gothic', 'AppleGothic'):
    if any(name in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = name
        break
plt.rcParams['axes.unicode_minus'] = False


def box(ax, x, y, w, h, text, fc, ec='#3b4a5a', fs=10, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.08',
                                fc=fc, ec=ec, lw=1.2))
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
            fontweight='bold' if bold else 'normal', linespacing=1.35)


def arrow(ax, a, b, text='', both=False, dy=0.12, dx=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle='<|-|>' if both else '-|>', mutation_scale=12,
                                 lw=1.2, color='#3b4a5a'))
    if text:
        ax.text((a[0]+b[0])/2+dx, (a[1]+b[1])/2+dy, text, ha='center', va='bottom', fontsize=8.5,
                color='#3b4a5a')


def system():
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis('off')

    # Host
    box(ax, 0.1, 1.4, 2.0, 2.0, 'PC (호스트)\n\n· 잡음 영상 7비트화\n· im2col / 재양자화\n· 최종 영상 복원', '#eef3f8')
    # Board outline
    ax.add_patch(FancyBboxPatch((2.9, 0.25), 6.95, 4.1, boxstyle='round,pad=0.02,rounding_size=0.1',
                                fc='none', ec='#8a96a3', lw=1.0, ls='--'))
    ax.text(3.05, 4.12, 'ZedBoard  (Zynq XC7Z020)', fontsize=9.5, color='#5a6774')
    # PS side
    box(ax, 3.2, 2.45, 2.1, 1.4, 'PS (ARM)\n+ DDR3 512 MB', '#f3f0e8')
    # PL side
    box(ax, 6.0, 2.45, 1.6, 1.4, 'AXI DMA\n(MM2S / S2MM)', '#e8f2ec')
    box(ax, 7.95, 1.0, 1.75, 2.85, 'CNN 코어\n(Bank, P=16, T=4)\n\n곱셈기 64개\nLUT로 구현\nDSP 0개', '#dbeafe',
        bold=False)
    box(ax, 3.2, 0.55, 4.4, 1.2, 'AXI4-Lite 제어 레지스터\nRUN_K / RUN_COUT / CTRL / STATUS / CYCLES', '#f6f6f6', fs=9)

    arrow(ax, (2.1, 2.9), (3.2, 3.15), 'JTAG\n(xsdb)', both=True, dy=0.18, dx=-0.15)
    arrow(ax, (5.3, 3.15), (6.0, 3.15), 'HP0', both=True)
    arrow(ax, (7.6, 3.4), (7.95, 3.4))
    ax.text(7.77, 3.5, '입력', fontsize=8, ha='center')
    arrow(ax, (7.95, 2.75), (7.6, 2.75))
    ax.text(7.77, 2.85, '출력', fontsize=8, ha='center')
    arrow(ax, (4.25, 2.45), (4.25, 1.75), 'GP0', dy=-0.1, dx=0.3)
    arrow(ax, (7.6, 1.15), (7.95, 1.15))
    ax.text(5.4, 0.3, '층마다 형상(K, COUT)만 바꿔 같은 비트스트림으로 모든 층을 실행', fontsize=8.5,
            ha='center', color='#5a6774')
    fig.tight_layout()
    fig.savefig(OUT/'fig_system.png', dpi=170)
    plt.close(fig)


def board_compare():
    import pymupdf
    src = ROOT/'denoise'/'figures'/'05_dn_d7_c32_board.pdf'
    pix = pymupdf.open(src)[0].get_pixmap(dpi=160)
    pix.save(OUT/'fig_board_compare.png')


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    system()
    board_compare()
    print(f'wrote {OUT}')
