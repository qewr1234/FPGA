"""Diagrams for the Korean explainer of PAPER_EN.md (EXPLAINER_KO.html).

    python3 bankperm/explainer/diagrams.py      # writes ex_*.png next to this file

Schematics with small, made-up numbers (stated in each figure) except ex_cost.png,
which plots equation (1) of the paper for the board network's hidden layers
(K = 288, COUT = 32, P = 16, T = 4). Colours are the paper's (figures/fig1_layouts.py).
"""
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

HERE = Path(__file__).resolve().parent
BLUE, ORANGE, AQUA, INK, MUTED = '#2a78d6', '#eb6834', '#1baf7a', '#0b0b0b', '#52514e'
YELLOW = '#eda100'
BANK = (MUTED, BLUE, AQUA, YELLOW)
ZERO = '#f5f4f1'
EDGE = '#9a9893'
FILL = '#f7f6f3'
TXT_IN = ('white', 'white', INK, INK)

plt.rcParams.update({'font.family': ['Noto Sans CJK KR', 'DejaVu Sans'], 'font.size': 9, 'axes.unicode_minus': False,
                     'hatch.linewidth': 0.5})


def save(fig, name):
    fig.savefig(HERE/name, dpi=220, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)
    print('wrote', HERE/name)


def bank_bars(ax, counts, x0, unit, bw=0.62, gap=0.18, label=True, total_h=None):
    """Bars of nonzero taps per bank, the lockstep idle part hatched."""
    m = max(counts)
    for b, n in enumerate(counts):
        x = x0 + b*(bw + gap)
        ax.add_patch(Rectangle((x, 0), bw, n*unit, fc=BANK[b], ec=INK if n == m else 'none', lw=1.0, zorder=3))
        if n < m:
            ax.add_patch(Rectangle((x, n*unit), bw, (m - n)*unit, fc='white', ec=MUTED, lw=0.5, hatch='////',
                                   zorder=2))
        ax.text(x + bw/2, n*unit - 0.08, str(n), ha='center', va='top', color=TXT_IN[b], fontsize=9, zorder=4)
        if label:
            ax.text(x + bw/2, -0.12, f'뱅크 {b}', ha='center', va='top', fontsize=8, color=INK)
    right = x0 + 4*(bw + gap) - gap
    ax.plot([x0 - 0.1, right + 0.1], [m*unit, m*unit], ls=(0, (3, 2)), lw=0.8, color=INK, zorder=4)
    return right


def ex_lockstep():
    """Two windows of 32 nonzero taps: imbalanced (lockstep waits for 12) and balanced (8)."""
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.6))
    cases = [([12, 5, 9, 6], '불균형한 창: 가장 바쁜 뱅크(12)를 모두 기다림'),
             ([8, 8, 8, 8], '균형 잡힌 창: 같은 32개 탭, 8사이클이면 끝')]
    for ax, (counts, title) in zip(axes, cases):
        ax.set_xlim(-0.4, 3.6); ax.set_ylim(-0.9, 4.4); ax.axis('off')
        right = bank_bars(ax, counts, 0.1, 0.3)
        m = max(counts)
        ax.text(right + 0.15, m*0.3, f'm = {m}', ha='left', va='center', fontsize=9, color=INK)
        ax.set_title(title, fontsize=9, color=INK, pad=4)
        ax.text(1.6, 4.2, f'0이 아닌 탭 {sum(counts)}개, 한 출력 그룹에 {m}사이클', ha='center', va='center',
                fontsize=8, color=MUTED)
    fig.text(0.5, -0.02, '빗금: 그 뱅크가 놀고 있는 사이클. 네 뱅크는 함께(lockstep) 다음 창으로 넘어간다.',
             ha='center', fontsize=8, color=MUTED)
    save(fig, 'ex_lockstep.png')


def ex_window():
    """im2col: a 3x3 window over N = 8 channels becomes K = 72 taps; tap (s, p) in slot s*N + p."""
    N = 8
    fig = plt.figure(figsize=(6.6, 2.9))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 13.4); ax.set_ylim(0.6, 5.8); ax.axis('off')
    # left: the 3x3 neighbourhood, a stack of N channel planes
    for p in range(N - 1, -1, -1):
        dx, dy = 0.16*p, 0.16*p
        for r in range(3):
            for c in range(3):
                s = r*3 + c
                ax.add_patch(Rectangle((0.4 + c*0.62 + dx, 3.6 - r*0.62 + dy), 0.6, 0.6, fc='white' if p else '#e8f0fb',
                                       ec=EDGE, lw=0.5, zorder=10 - p))
                if p == 0:
                    ax.text(0.7 + c*0.62, 3.9 - r*0.62, f's={s}', ha='center', va='center', fontsize=6.5, zorder=20)
    ax.text(1.6, 1.25, '출력 픽셀 하나에 쓰이는 3×3 이웃\n× 입력 채널 N개(여기서는 8)', ha='center', va='top', fontsize=8)
    ax.text(2.95, 5.45, f'채널 p = 0 … {N - 1}', ha='center', fontsize=7.5, color=MUTED)
    ax.add_patch(FancyArrowPatch((3.9, 3.6), (5.0, 3.6), arrowstyle='-|>', mutation_scale=10, lw=1.0, color=INK))
    ax.text(4.45, 3.85, 'im2col', ha='center', fontsize=8)
    # right: the window as 9 rows of N slots, coloured by bank under L0 (slot j -> bank j mod 4)
    x0, y0, cs = 5.9, 4.95, 0.34
    for s in range(9):
        for p in range(N):
            j = s*N + p
            ax.add_patch(Rectangle((x0 + p*cs, y0 - s*cs*1.02), cs*0.92, cs*0.92, fc=BANK[j % 4], ec='none'))
        ax.text(x0 - 0.12, y0 - s*cs*1.02 + cs*0.45, f'{s}', ha='right', va='center', fontsize=6.5)
    ax.text(x0 - 0.45, y0 - 4*cs*1.02 + cs*0.45, 's', ha='right', va='center', fontsize=8)
    for p in range(N):
        ax.text(x0 + p*cs + cs*0.45, y0 + cs*1.15, str(p), ha='center', fontsize=6.5)
    ax.text(x0 + N*cs/2, y0 + cs*1.9, '채널 p', ha='center', fontsize=8)
    ax.text(x0 + N*cs/2, 1.6, '창 = K = 9N = 72개 탭\n탭 (s, p)는 슬롯 j = s·N + p', ha='center', va='top', fontsize=8)
    # legend: bank = j mod 4
    lx = 9.6
    ax.text(lx, 5.2, '슬롯 j는 뱅크 j mod 4', fontsize=8.5, fontweight='bold')
    for b in range(4):
        ax.add_patch(Rectangle((lx, 4.55 - b*0.42), 0.3, 0.3, fc=BANK[b], ec='none'))
        ax.text(lx + 0.42, 4.7 - b*0.42, f'뱅크 {b}', va='center', fontsize=8)
    ax.text(lx, 2.6, 'N이 4의 배수이면 j mod 4 = p mod 4:\n한 채널의 9개 탭이 모두\n같은 뱅크에 간다(L0).',
            va='top', fontsize=8, color=INK, linespacing=1.4)
    save(fig, 'ex_window.png')


def ex_layouts():
    """L0 against L2 for N = 8: bank of tap (s, p), and where one channel's nine taps go."""
    N = 8
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.2))
    for ax, (title, rule) in zip(axes, [('L0 (기존): 뱅크 = p mod 4', lambda s, p: p % 4),
                                        ('L2 (skew): 뱅크 = (p + s) mod 4', lambda s, p: (p + s) % 4)]):
        ax.set_xlim(-1.4, N + 0.2); ax.set_ylim(-2.6, 9.9); ax.axis('off'); ax.set_aspect('equal')
        for s in range(9):
            for p in range(N):
                b = rule(s, p)
                ax.add_patch(Rectangle((p, 8 - s), 0.92, 0.92, fc=BANK[b], ec='none'))
                ax.text(p + 0.46, 8 - s + 0.46, str(b), ha='center', va='center', fontsize=6.5, color=TXT_IN[b])
            ax.text(-0.25, 8 - s + 0.46, str(s), ha='right', va='center', fontsize=7)
        ax.add_patch(Rectangle((1 - 0.06, -0.06), 1.04, 9.04, fc='none', ec=ORANGE, lw=1.6))
        for p in range(N):
            ax.text(p + 0.46, 9.25, str(p), ha='center', fontsize=7)
        ax.text(N/2, 9.95, '채널 p', ha='center', fontsize=8)
        ax.text(-1.0, 4.5, '위치 s', rotation=90, ha='center', va='center', fontsize=8)
        ax.set_title(title, fontsize=9, pad=14)
        counts = [sum(1 for s in range(9) if rule(s, 1) == b) for b in range(4)]
        ax.text(N/2, -0.6, '채널 1(주황 테두리)의 9개 탭,\n뱅크 0/1/2/3에: ' + ' / '.join(str(c) for c in counts),
                ha='center', va='top', fontsize=7.5, color=INK, linespacing=1.3)
    fig.text(0.5, 0.02, '칸 안의 숫자는 그 탭의 뱅크. 자주 켜지는 채널이 있으면 L0에서는 그 채널의 탭이 한 뱅크에 몰리고, '
             'L2에서는 3/2/2/2로 흩어진다.', ha='center', fontsize=7.5, color=MUTED, wrap=True)
    save(fig, 'ex_layouts.png')


def ex_cost():
    """Equation (1) for K = 288, COUT = 32 (P = 16): C against m at W = 1, 2, 4."""
    K, COUT, P, T = 288, 32, 16, 4
    g = math.ceil(COUT/P)
    ms = list(range(0, math.ceil(K/T) + 1))
    fig, ax = plt.subplots(figsize=(6.0, 3.1))
    styles = {1: (MUTED, '-'), 2: (AQUA, '-'), 4: (BLUE, '-')}
    for w in (1, 2, 4):
        load = math.ceil(K/w) + 1
        c = [max(load, g*max(1, m), COUT) for m in ms]
        ax.plot(ms, c, color=styles[w][0], lw=1.8, label=f'W = {w}: 적재 바닥 {load}사이클')
    ax.plot(ms, [g*max(1, m) for m in ms], color=INK, lw=0.8, ls=(0, (3, 2)), label='계산 2·m (출력 32개 = 2그룹)')
    ax.axvline(36.5, color=MUTED, lw=0.6, ls=':')
    ax.annotate('m = 36.5에서 2m = 73\n(W = 4의 적재와 같아짐)', (36.5, 73), xytext=(4, 100), fontsize=7.5,
                arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.6))
    for m, txt, dy in ((47.6, 'L0 평균 m 47.6', 12), (39.7, 'L3 평균 m 39.7', -26)):
        ax.plot([m], [2*m], 'o', ms=4, color=ORANGE, zorder=5)
        ax.annotate(txt, (m, 2*m), xytext=(m + 2, 2*m + dy), fontsize=7.5, color=ORANGE)
    ax.text(72, 150, 'm ≤ ⌈K/T⌉ = 72이므로\n계산은 최대 144사이클:\nW = 1, 2에서는 늘 적재가 더 김',
            ha='right', va='bottom', fontsize=7.5, color=INK)
    ax.set_xlabel('m (가장 바쁜 뱅크의 0이 아닌 탭 수)'); ax.set_ylabel('창 하나의 사이클 C')
    ax.set_xlim(0, 72); ax.set_ylim(0, 310)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    ax.legend(fontsize=7.5, frameon=False, loc='upper left', bbox_to_anchor=(0.0, 0.88))
    ax.set_title('식 (1): K = 288, COUT = 32인 숨은 층(보드 망 conv2–conv9)', fontsize=9)
    save(fig, 'ex_cost.png')


def ex_relabel():
    """Folding a channel relabeling: producer rows and consumer columns move together."""
    fig = plt.figure(figsize=(6.6, 2.5))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 13.2); ax.set_ylim(0, 5); ax.axis('off')
    cols = [BLUE, ORANGE, AQUA, YELLOW]
    names = ['a', 'b', 'c', 'd']
    order = [2, 0, 3, 1]          # pi: position q holds original channel order[q]

    def column(x, y, items, title, sub):
        for i, k in enumerate(items):
            ax.add_patch(Rectangle((x, y - i*0.62), 1.3, 0.55, fc=cols[k], ec='none'))
            ax.text(x + 0.65, y - i*0.62 + 0.27, f'채널 {names[k]}', ha='center', va='center', fontsize=7.5,
                    color='white' if k in (0, 1) else INK)
        ax.text(x + 0.65, y + 0.9, title, ha='center', fontsize=8.5, fontweight='bold')
        ax.text(x + 0.65, y - 4*0.62 + 0.25, sub, ha='center', va='top', fontsize=7, color=MUTED, linespacing=1.3)

    column(0.5, 3.4, [0, 1, 2, 3], '원래 생산자 층', '출력 채널 순서\na, b, c, d')
    column(4.2, 3.4, order, '재배치한 생산자 층', '가중치 행·바이어스·\n재양자화 스케일을\nπ 순서로')
    column(7.9, 3.4, order, '숨은 맵', '같은 값, 채널 순서만\n바뀜: 위치 q마다\n다른 뱅크 그룹')
    ax.add_patch(FancyArrowPatch((2.0, 2.5), (4.0, 2.5), arrowstyle='-|>', mutation_scale=10, lw=1, color=INK))
    ax.text(3.0, 2.75, 'π로 접기', ha='center', fontsize=8)
    ax.add_patch(FancyArrowPatch((5.7, 2.5), (7.7, 2.5), arrowstyle='-|>', mutation_scale=10, lw=1, color=INK))
    ax.add_patch(FancyArrowPatch((9.4, 2.5), (10.6, 2.5), arrowstyle='-|>', mutation_scale=10, lw=1, color=INK))
    ax.add_patch(FancyBboxPatch((10.7, 1.3), 2.3, 2.6, boxstyle='round,pad=0.05,rounding_size=0.15', fc=FILL, ec=EDGE,
                                lw=0.6))
    ax.text(11.85, 3.55, '소비자 층', ha='center', fontsize=8.5, fontweight='bold')
    ax.text(11.85, 3.15, '가중치 열도 같은\nπ로 바꿔 둠\n→ 같은 곱을 더함\n→ 정수 출력 동일', ha='center',
            va='top', fontsize=7.5, linespacing=1.35)
    save(fig, 'ex_relabel.png')


def ex_decouple():
    """Lockstep against decoupled banks over three windows: transient and persistent imbalance."""
    cases = [('불균형이 창마다 다른 뱅크로 옮겨 다닐 때', [[6, 2, 2, 2], [2, 6, 2, 2], [2, 2, 6, 2]]),
             ('불균형이 늘 같은 뱅크에 있을 때(L0의 실제 모습)', [[6, 2, 4, 3], [5, 3, 2, 4], [6, 2, 3, 2]])]
    fig, axes = plt.subplots(2, 2, figsize=(6.8, 3.9), gridspec_kw=dict(hspace=0.75, wspace=0.12))
    wcol = ['#cfe0f6', '#fde0c8', '#d3f0e4']
    for r, (title, wins) in enumerate(cases):
        lock = [max(w) for w in wins]
        for c, mode in enumerate(('lockstep', 'decoupled')):
            ax = axes[r][c]
            t_end = 0
            for b in range(4):
                t = 0
                for wi, w in enumerate(wins):
                    if mode == 'lockstep':
                        start = sum(lock[:wi])
                        ax.add_patch(Rectangle((start, b), w[b], 0.8, fc=wcol[wi], ec=EDGE, lw=0.4))
                        if w[b] < lock[wi]:
                            ax.add_patch(Rectangle((start + w[b], b), lock[wi] - w[b], 0.8, fc='white', ec=MUTED,
                                                   lw=0.4, hatch='////'))
                        ax.text(start + w[b]/2, b + 0.4, str(w[b]), ha='center', va='center', fontsize=6.5)
                    else:
                        ax.add_patch(Rectangle((t, b), w[b], 0.8, fc=wcol[wi], ec=EDGE, lw=0.4))
                        ax.text(t + w[b]/2, b + 0.4, str(w[b]), ha='center', va='center', fontsize=6.5)
                        t += w[b]
                t_end = max(t_end, t if mode == 'decoupled' else sum(lock))
            ax.plot([t_end, t_end], [-0.2, 4.05], color=INK, lw=0.9)
            ax.text(t_end, 4.15, f'{t_end}사이클', fontsize=7.5, va='bottom', ha='center')
            ax.set_xlim(0, 21); ax.set_ylim(-0.2, 4.7)
            ax.set_yticks([b + 0.4 for b in range(4)]); ax.set_yticklabels([f'뱅크{b}' for b in range(4)], fontsize=7)
            ax.tick_params(axis='x', labelsize=6.5, length=2); ax.tick_params(axis='y', length=0)
            for sp in ('top', 'right', 'left'):
                ax.spines[sp].set_visible(False)
            ax.set_title(('lockstep (지금 코어)' if mode == 'lockstep' else '뱅크마다 큐(FIFO), 버퍼 무한'),
                         fontsize=8, pad=3)
        axes[r][0].text(-0.08, 1.32, f'({"가나"[r]}) {title}', transform=axes[r][0].transAxes, fontsize=8.5,
                        fontweight='bold', ha='left')
    fig.text(0.5, -0.02, '색: 창 1·2·3, 숫자: 그 창에서 그 뱅크의 0이 아닌 탭 수(한 그룹), 빗금: lockstep의 대기. '
             '적재 시간은 그리지 않았다.', ha='center', fontsize=7.5, color=MUTED)
    save(fig, 'ex_decouple.png')


if __name__ == '__main__':
    ex_lockstep(); ex_window(); ex_layouts(); ex_cost(); ex_relabel(); ex_decouple()
