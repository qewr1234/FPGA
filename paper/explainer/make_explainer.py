"""Build EXPLAINER_KO.pdf: the project explained so a child could follow it,
plus where the paper should go from here.

    python paper/explainer/make_explainer.py

Every number comes from paper/figures/data.py, so this document cannot drift
from the paper. If paper/figures/fig9_classified.png exists (it is made on the
machine that ran the board), it is placed in the document; otherwise a note
says where it will appear.

Needs matplotlib and reportlab (pip install reportlab), and a font with Hangul:
Malgun Gothic on Windows is found automatically.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIG = ROOT/'paper'/'figures'
sys.path.insert(0, str(FIG))
import data  # noqa: E402  every number in this document comes from here

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch, Polygon  # noqa: E402

# ------------------------------------------------------------------ fonts ---
FONT_CANDIDATES = [
    ('C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf', None),
    ('/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
     '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf', None),
    ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
     '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 1),
    ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', None, 0),
]


def find_font():
    for reg, bold, idx in FONT_CANDIDATES:
        if Path(reg).exists():
            return reg, (bold if bold and Path(bold).exists() else reg), idx
    raise SystemExit('No font with Hangul found. On Windows, Malgun Gothic '
                     '(C:/Windows/Fonts/malgun.ttf) is normally present.')


FONT_REG, FONT_BOLD, FONT_IDX = find_font()
font_manager.fontManager.addfont(FONT_REG)
MPL_FAMILY = font_manager.FontProperties(fname=FONT_REG).get_name()
plt.rcParams.update({'font.family': MPL_FAMILY, 'axes.unicode_minus': False,
                     'font.size': 11})

# ----------------------------------------------------------------- colour ---
# The paper's palette, validated (worst adjacent CVD dE 11.0, normal 25.8).
BLUE, VERM, GREEN = '#0072B2', '#D55E00', '#009E73'
INK, INK2, MUTED, FILL = '#1a1a1a', '#4d4d4d', '#8c8c8c', '#e8eef2'
PALE_BLUE, PALE_VERM, PALE_GREEN = '#d6e6f2', '#f7dccb', '#d2eee5'

OUT = HERE/'build'
OUT.mkdir(exist_ok=True)


def save(fig, name):
    p = OUT/f'{name}.png'
    fig.savefig(p, dpi=200, bbox_inches='tight', pad_inches=0.08, facecolor='white')
    plt.close(fig)
    return p


def box(ax, x, y, w, h, text, fc=FILL, ec=INK2, size=12, bold=False, color=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.08',
                                fc=fc, ec=ec, lw=1.2))
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=size,
            color=color, fontweight='bold' if bold else 'normal')


def arrow(ax, x0, y0, x1, y1, color=INK2):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle='-|>',
                                 mutation_scale=16, lw=1.6, color=color))


def blank(ax, w, h):
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.set_aspect('equal'); ax.axis('off')


# ---------------------------------------------------------------- figures ---
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(8, 2.2)); blank(ax, 16, 4.2)
    # a tiny "cat" picture made of squares
    rng = [[.85, .80, .75, .8], [.70, .45, .45, .7], [.65, .40, .42, .6], [.8, .7, .7, .75]]
    for i in range(4):
        for j in range(4):
            g = rng[i][j]
            ax.add_patch(Rectangle((0.4+j*0.7, 0.4+(3-i)*0.7), 0.68, 0.68,
                                   fc=(g, g*0.9, g*0.75), ec='white', lw=0.5))
    ax.text(1.8, 3.55, '사진 (32×32 점)', ha='center', fontsize=11, color=INK)
    arrow(ax, 3.4, 1.8, 5.0, 1.8)
    box(ax, 5.1, 0.5, 5.2, 2.6, 'FPGA 칩\n(우리가 만든 계산기)', fc=PALE_VERM, ec=VERM, size=13, bold=True)
    arrow(ax, 10.4, 1.8, 12.0, 1.8)
    box(ax, 12.1, 1.0, 3.5, 1.6, '"고양이!"', fc=PALE_GREEN, ec=GREEN, size=15, bold=True)
    return save(fig, 'f1_pipeline')


def fig_window():
    fig, ax = plt.subplots(figsize=(8, 3.2)); blank(ax, 16, 6.2)
    vals = [[0, 3, 5, 2, 0, 1], [4, 7, 0, 6, 3, 0], [1, 0, 8, 2, 5, 4],
            [0, 6, 3, 0, 2, 7], [5, 2, 0, 4, 1, 0], [3, 0, 6, 1, 0, 2]]
    s = 0.9
    for i in range(6):
        for j in range(6):
            inwin = 1 <= i <= 3 and 1 <= j <= 3
            ax.add_patch(Rectangle((0.3+j*s, 0.3+(5-i)*s), s, s,
                                   fc=PALE_BLUE if inwin else 'white', ec=MUTED, lw=0.8))
            ax.text(0.3+j*s+s/2, 0.3+(5-i)*s+s/2, str(vals[i][j]), ha='center',
                    va='center', fontsize=11, color=INK)
    ax.add_patch(Rectangle((0.3+1*s, 0.3+2*s), 3*s, 3*s, fill=False, ec=BLUE, lw=3))
    ax.text(0.3+3*s, 5.95, '돋보기 창 (3×3)', ha='center', fontsize=11, color=INK)
    arrow(ax, 6.0, 3.2, 7.4, 3.2)
    ax.text(7.6, 4.3, '창 안의 숫자 × 정해진 무게(가중치)', fontsize=12, color=INK)
    ax.text(7.6, 3.2, '→ 전부 더하기 = 특징 점수 1개', fontsize=12, color=INK)
    ax.text(7.6, 2.1, '창을 한 칸씩 옮기며 그림 전체를 훑는다', fontsize=12, color=INK2)
    ax.text(7.6, 1.0, '곱하기·더하기가 사진 한 장에 3,863만 번!', fontsize=12,
            color=VERM, fontweight='bold')
    return save(fig, 'f2_window')


def fig_lego():
    fig, ax = plt.subplots(figsize=(8, 3.3)); blank(ax, 16, 6.6)
    ax.text(3.6, 6.1, '칩 안의 전용 계산기 (DSP)', ha='center', fontsize=12, color=INK, fontweight='bold')
    for r in range(3):
        for c in range(5):
            x, y = 0.4+c*1.4, 3.4-r*1.2
            box(ax, x, y, 1.2, 0.95, '사용중', fc='#eeeeee', ec=MUTED, size=9, color=INK2)
    ax.text(3.6, 0.35, '이미 다른 일(필터·영상 처리)을 하는 중', ha='center', fontsize=10.5, color=INK2)
    ax.plot([8, 8], [0.3, 6.3], color=MUTED, lw=1, ls=':')
    ax.text(12.1, 6.1, '레고 블록 (LUT)으로 조립', ha='center', fontsize=12, color=INK, fontweight='bold')
    for r in range(4):
        for c in range(7):
            ax.add_patch(Rectangle((9.0+c*0.9, 1.5+r*0.9), 0.8, 0.8, fc=PALE_VERM, ec=VERM, lw=0.9))
    box(ax, 10.6, 2.6, 3.0, 1.3, '곱셈기', fc='white', ec=VERM, size=13, bold=True)
    ax.text(12.1, 0.35, '작은 블록을 모아 계산기를 직접 만든다', ha='center', fontsize=10.5, color=INK2)
    return save(fig, 'f3_lego')


def fig_skip():
    fig, ax = plt.subplots(figsize=(8, 1.9)); blank(ax, 16, 3.6)
    row = [3, 0, 5, 0, 0, 2, 7, 0, 1, 0]
    for k, v in enumerate(row):
        x = 0.4+k*1.5
        z = v == 0
        box(ax, x, 1.4, 1.2, 1.2, str(v), fc='#f2f2f2' if z else PALE_BLUE,
            ec=MUTED if z else BLUE, size=15, color=MUTED if z else INK)
        if z:
            ax.plot([x+0.1, x+1.1], [1.5, 2.5], color=VERM, lw=2.2)
            ax.plot([x+0.1, x+1.1], [2.5, 1.5], color=VERM, lw=2.2)
    ax.text(0.4, 0.5, '0 × 무엇 = 0  →  0인 칸은 계산을 건너뛴다.  이 칸들 중 절반가량이 0이다.',
            fontsize=12, color=INK)
    return save(fig, 'f4_skip')


def fig_workers():
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4))
    for ax in axes:
        blank(ax, 8, 6.4)
    a, b = axes
    a.text(4, 6.0, 'Channel 방식', ha='center', fontsize=13, fontweight='bold', color=INK)
    for k in range(4):
        x = 0.3+k*1.95
        box(a, x, 3.4, 1.6, 1.0, f'일꾼{k+1}', fc=PALE_BLUE, ec=BLUE, size=10)
        arrow(a, x+0.8, 3.35, x+0.8, 2.55)
        box(a, x, 1.4, 1.6, 1.1, '공책', fc='white', ec=INK2, size=10)
    a.text(4, 0.5, '일꾼마다 공책(32비트 누산기)이 하나씩', ha='center', fontsize=10.5, color=INK2)
    b.text(4, 6.0, 'Bank 방식', ha='center', fontsize=13, fontweight='bold', color=INK)
    for k in range(4):
        x = 0.3+k*1.95
        box(b, x, 4.2, 1.6, 1.0, f'일꾼{k+1}', fc=PALE_VERM, ec=VERM, size=10)
        arrow(b, x+0.8, 4.15, 3.2+0.4*k, 3.25)
    box(b, 2.6, 2.3, 2.8, 0.9, '더하기', fc='white', ec=INK2, size=11)
    arrow(b, 4.0, 2.25, 4.0, 1.75)
    box(b, 3.1, 0.95, 1.8, 0.8, '공책', fc='white', ec=INK2, size=10)
    b.text(4, 0.25, '먼저 더한 뒤 공책은 하나만', ha='center', fontsize=10.5, color=INK2)
    return save(fig, 'f5_workers')


def fig_cost():
    iso = data.ISO64
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    rows = [('레고 블록 (LUT)', iso['v3']['lut'], iso['v4']['lut']),
            ('기억 칸 (플립플롭)', iso['v3']['ff'], iso['v4']['ff'])]
    y = [1, 0]
    h = 0.34
    for yi, (name, c, bk) in zip(y, rows):
        ax.barh(yi+h/2+0.02, c, height=h, color=BLUE, label='Channel' if yi == 1 else None)
        ax.barh(yi-h/2-0.02, bk, height=h, color=VERM, label='Bank' if yi == 1 else None)
        ax.text(c+120, yi+h/2+0.02, f'{c:,.0f}', va='center', fontsize=10.5, color=INK)
        ax.text(bk+120, yi-h/2-0.02, f'{bk:,.0f}  ({(bk/c-1)*100:+.0f}%)', va='center',
                fontsize=10.5, color=INK, fontweight='bold')
    ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.set_xlim(0, 10500)
    ax.set_xlabel('곱셈기 64개를 만들 때 드는 양 (적을수록 좋음)', fontsize=10.5, color=INK2)
    for sd in ('top', 'right'):
        ax.spines[sd].set_visible(False)
    ax.grid(axis='x', color=MUTED, alpha=0.3, lw=0.5); ax.set_axisbelow(True)
    ax.legend(loc='lower right', frameon=False, fontsize=10.5)
    return save(fig, 'f6_cost')


def fig_room():
    L = data.cifar_layers()
    kmax = data.CIFAR['built_k']
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    names = [l['name'] for l in L][::-1]
    ks = [l['K'] for l in L][::-1]
    ax.barh(names, [kmax]*len(ks), color=FILL, height=0.62, label=f'지어 둔 크기 ({kmax}칸)')
    ax.barh(names, ks, color=BLUE, height=0.62, label='이 층이 실제로 쓰는 칸')
    for n, k in zip(names, ks):
        ax.text(min(k, kmax)+15, n, f'{k}', va='center', fontsize=10, color=INK)
    ax.set_xlim(0, kmax*1.08)
    ax.set_xlabel('한 번에 보는 숫자 개수 (K)', fontsize=10.5, color=INK2)
    for sd in ('top', 'right'):
        ax.spines[sd].set_visible(False)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, fontsize=10)
    return save(fig, 'f7_room')


def fig_funnel():
    L = data.cifar_layers()
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    names = [l['name'] for l in L]
    ratio = [l['cycles_per_window']/l['K'] for l in L]
    x = range(len(L))
    ax.bar(x, ratio, color=VERM, width=0.55, label='실제로 걸린 시간 ÷ 입구 한계')
    ax.axhline(1.0, color=INK, lw=1.4, ls='--', label='입구 한계 (1.0 = 한계와 똑같음)')
    for xi, r in zip(x, ratio):
        ax.text(xi, r+0.012, f'{r:.3f}', ha='center', fontsize=10, color=INK)
    ax.set_xticks(list(x)); ax.set_xticklabels(names, fontsize=10.5)
    ax.set_ylim(0.9, 1.26)
    ax.set_ylabel('배수', fontsize=10.5, color=INK2)
    for sd in ('top', 'right'):
        ax.spines[sd].set_visible(False)
    ax.grid(axis='y', color=MUTED, alpha=0.3, lw=0.5); ax.set_axisbelow(True)
    ax.legend(loc='upper right', frameon=False, fontsize=10)
    return save(fig, 'f8_funnel')


def fig_funnel_picture():
    fig, ax = plt.subplots(figsize=(8, 2.8)); blank(ax, 16, 5.6)
    for k in range(6):
        ax.add_patch(Rectangle((0.3+k*0.6, 4.1), 0.5, 0.5, fc=PALE_BLUE, ec=BLUE))
    ax.text(2.0, 4.95, '기다리는 숫자들', ha='center', fontsize=10.5, color=INK)
    ax.add_patch(Polygon([[0.2, 3.8], [3.9, 3.8], [2.3, 2.3], [1.8, 2.3]], closed=True,
                         fc='#f2f2f2', ec=INK2, lw=1.2))
    ax.add_patch(Rectangle((1.8, 1.2), 0.5, 1.1, fc='#f2f2f2', ec=INK2, lw=1.2))
    ax.add_patch(Rectangle((1.82, 1.4), 0.46, 0.46, fc=PALE_BLUE, ec=BLUE))
    ax.text(2.05, 0.6, '입구: 한 번에 1개', ha='center', fontsize=10.5, color=VERM, fontweight='bold')
    arrow(ax, 2.6, 1.6, 5.0, 1.6)
    for k in range(8):
        box(ax, 5.3+(k % 4)*1.3, 2.9-(k//4)*1.3, 1.1, 1.0, '일꾼', fc=PALE_VERM, ec=VERM, size=9)
    ax.text(7.8, 4.55, '일꾼 64명 (곱셈기)', ha='center', fontsize=10.5, color=INK)
    ax.text(10.9, 2.9, '일꾼은 충분히 빠른데', fontsize=11.5, color=INK)
    ax.text(10.9, 2.1, '입구가 좁아서 기다린다.', fontsize=11.5, color=INK)
    ax.text(10.9, 1.0, '→ 일꾼을 늘려도 5%만 빨라짐', fontsize=11.5, color=VERM, fontweight='bold')
    return save(fig, 'f9_funnel_pic')


# --------------------------------------------------------------- document ---
def build():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    Table, TableStyle, PageBreak, KeepTogether)

    kw = {'subfontIndex': FONT_IDX} if FONT_IDX is not None else {}
    pdfmetrics.registerFont(TTFont('KR', FONT_REG, **kw))
    pdfmetrics.registerFont(TTFont('KRB', FONT_BOLD, **kw))

    W = A4[0] - 36*mm
    st = dict(
        title=ParagraphStyle('t', fontName='KRB', fontSize=22, leading=30, textColor=INK, spaceAfter=4),
        sub=ParagraphStyle('s', fontName='KR', fontSize=11.5, leading=17, textColor=INK2, spaceAfter=12),
        h1=ParagraphStyle('h1', fontName='KRB', fontSize=16, leading=22, textColor=INK,
                          spaceBefore=10, spaceAfter=6),
        h2=ParagraphStyle('h2', fontName='KRB', fontSize=12.5, leading=18, textColor=INK,
                          spaceBefore=8, spaceAfter=4),
        body=ParagraphStyle('b', fontName='KR', fontSize=11, leading=17.5, textColor=INK, spaceAfter=6),
        small=ParagraphStyle('sm', fontName='KR', fontSize=9.5, leading=14, textColor=INK2, spaceAfter=4),
        box=ParagraphStyle('bx', fontName='KR', fontSize=11, leading=17, textColor=INK),
        cell=ParagraphStyle('c', fontName='KR', fontSize=10, leading=14, textColor=INK),
        cellb=ParagraphStyle('cb', fontName='KRB', fontSize=10, leading=14, textColor=INK),
    )
    P = lambda t, s='body': Paragraph(t, st[s])

    def img(path, width=W):
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(str(path)).getSize()
        return Image(str(path), width=width, height=width*ih/iw)

    def callout(html, bg='#f3f7fa', edge=BLUE):
        t = Table([[Paragraph(html, st['box'])]], colWidths=[W])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg)),
                               ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor(edge)),
                               ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                               ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
        return t

    def table(rows, widths, head=True):
        t = Table([[Paragraph(str(c), st['cellb' if (head and i == 0) else 'cell']) for c in r]
                   for i, r in enumerate(rows)], colWidths=widths)
        style = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#c8c8c8')),
                 ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                 ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]
        if head:
            style.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2f5')))
        t.setStyle(TableStyle(style))
        return t

    C, S, iso = data.CIFAR, data.SYSTEM, data.ISO64
    floor = data.cifar_feed_floor()
    figs = dict(pipe=fig_pipeline(), win=fig_window(), lego=fig_lego(), skip=fig_skip(),
                workers=fig_workers(), cost=fig_cost(), room=fig_room(),
                funnelpic=fig_funnel_picture(), funnel=fig_funnel())

    s = []
    # ---------------------------------------------------------------- cover
    s += [P('작은 칩에 "그림 알아맞히기 두뇌" 넣기', 'title'),
          P('FPGA CNN 가속기 프로젝트를 초등학생도 알 수 있게 — 그리고 논문은 어디로 가야 하나', 'sub'),
          img(figs['pipe']),
          Spacer(1, 6),
          callout(f'<b>한 줄 요약.</b> 사진을 보고 "고양이", "자동차"를 알아맞히는 인공지능을 '
                  f'손바닥만 한 칩(FPGA) 안에 직접 만든 계산기로 돌렸다. 사진 {C["images"]}장을 '
                  f'보여줬더니 <b>{C["board_correct"]}장</b>을 맞혔고, 칩이 낸 '
                  f'<b>{C["outputs_compared"]:,}개</b>의 계산 답 가운데 컴퓨터로 확인한 정답과 '
                  f'다른 것은 <b>하나도 없었다</b>.'),
          Spacer(1, 10),
          P('이 문서의 순서', 'h2'),
          P('1. CNN은 그림을 어떻게 보나 &nbsp; 2. FPGA는 무엇이고 왜 레고로 만들었나 &nbsp; '
            '3. 0 건너뛰기 &nbsp; 4. 일꾼을 어떻게 배치할까 &nbsp; 5. 칩 하나로 여섯 층 전부 &nbsp; '
            '6. 결과 &nbsp; 7. 뜻밖의 발견: 입구가 좁다 &nbsp; 8. 솔직하게 말할 것 &nbsp; '
            '9. <b>논문은 이렇게 쓰자</b>'),
          PageBreak()]

    # ------------------------------------------------------------ 1. CNN
    s += [P('1. CNN은 그림을 어떻게 보나', 'h1'),
          P('컴퓨터에게 사진은 숫자가 빽빽하게 적힌 모눈종이다. CNN(합성곱 신경망)은 작은 '
            '<b>돋보기 창</b>을 이 모눈종이 위에서 한 칸씩 옮기며 "여기 뾰족한 귀 모양이 있나?", '
            '"여기 바퀴처럼 둥근 게 있나?"를 점수로 매긴다.'),
          img(figs['win']),
          P('점수를 매기는 방법은 단순하다. 창 안의 숫자마다 미리 배워 둔 <b>무게(가중치)</b>를 '
            '곱하고, 그걸 전부 더한다. 이 "곱하고 더하기"를 층을 바꿔 가며 여섯 번 반복하면 마지막에 '
            '"고양이일 점수가 제일 높다"가 나온다.'),
          callout(f'어려운 건 계산 방법이 아니라 <b>양</b>이다. 사진 한 장에 곱하기·더하기가 '
                  f'<b>{C["macs_per_image"]:,}번</b> 필요하다. 사람이 1초에 한 번씩 하면 '
                  f'1년 3개월이 걸린다.', bg='#fbf1ea', edge=VERM),
          PageBreak()]

    # ----------------------------------------------------------- 2. FPGA
    s += [P('2. FPGA는 무엇이고, 왜 레고로 만들었나', 'h1'),
          P('보통 컴퓨터 칩(CPU)은 공장에서 모양이 정해져 나온다. <b>FPGA</b>는 다르다. 안에 아주 작은 '
            '블록이 수만 개 들어 있고, 그걸 어떻게 연결할지를 우리가 정한다. 레고처럼 원하는 기계를 '
            '조립하는 칩이다. 우리가 쓴 칩(Zynq-7020)에는 레고 블록(LUT)이 53,200개 있다.'),
          P('FPGA에는 곱셈만 잘하는 <b>전용 계산기(DSP)</b>도 220개 들어 있다. 그런데 실제 기계에서 '
            'FPGA를 쓰는 이유는 보통 따로 있다. 전파 신호를 거르거나, 카메라 영상을 다듬거나, 모터를 '
            '제어하는 일이다. 그런 일이 이 전용 계산기를 먼저 차지한다.'),
          img(figs['lego']),
          P('그래서 이 프로젝트는 "전용 계산기는 다른 일에 쓰이고 있다"고 보고, <b>곱셈기를 전부 레고 '
            f'블록으로 조립했다</b>. 실제로 CNN을 돌린 설계는 전용 계산기를 <b>{S["dsp"]}개</b> 썼다.'),
          callout('<b>솔직히 덧붙이면.</b> 우리 실험에서 전용 계산기가 정말 다른 일을 하고 있었던 건 '
                  '아니다. 레고로만 만들게 한 진짜 이유는 <b>공정한 비교</b>였다. 두 설계 중 한쪽만 '
                  '전용 계산기를 몰래 쓰면 레고 개수를 비교할 수가 없다. 그리고 보드 빌드에서 0개가 '
                  '나온 건 "쓰지 마"라고 명령해서가 아니라 도구가 스스로 그렇게 고른 결과다. 논문에도 이 '
                  '두 가지를 그대로 적었다.'),
          PageBreak()]

    # ----------------------------------------------------------- 3. skip
    s += [P('3. 0 건너뛰기', 'h1'),
          P('CNN의 중간 층에서는 숫자 중 상당수가 <b>0</b>이다. "여기엔 그 모양이 없다"는 뜻이다. '
            '0에 무엇을 곱해도 0이므로, 우리 계산기는 0을 만나면 곱셈을 하지 않고 넘어간다.'),
          img(figs['skip']),
          P('이 네트워크의 마지막 층에서는 숫자의 <b>87.5%가 0</b>이었다(0이 아닌 것이 12.5%). 그만큼 '
            '곱셈을 안 해도 된다. 다만 이 절약에는 조건이 붙는다는 것이 7장에서 나온다.'),
          Spacer(1, 6),

          P('4. 일꾼을 어떻게 배치할까', 'h1'),
          P('곱셈기를 <b>일꾼</b>이라고 하자. 우리는 일꾼 64명을 쓸 수 있다. 일꾼을 배치하는 방법이 두 '
            '가지 있다.'),
          img(figs['workers'], width=W*0.88),
          P('<b>Channel 방식</b>은 일꾼마다 자기 답을 적을 공책을 하나씩 준다. <b>Bank 방식</b>은 일꾼 여럿이 '
            '먼저 답을 더하고, 공책은 하나만 쓴다. 이 "공책"(32비트 누산기)이 생각보다 비싸다.'),
          img(figs['cost'], width=W*0.8),
          P(f'같은 일꾼 64명인데 Bank 방식이 레고를 <b>29%</b>, 기억 칸을 <b>57%</b> 덜 쓴다. 게다가 '
            f'회로가 단순해서 더 빠른 박자로 돌 수 있어, 윈도우 하나를 끝내는 시간도 '
            f'{iso["v3"]["us_per_window"]:.2f}µs 대 <b>{iso["v4"]["us_per_window"]:.2f}µs</b>로 '
            f'4.4% 짧다. 작으면서 빠르다.'),
          P('유명한 선행 연구(Ma 등, 2017·2018)는 이 Bank 쪽 방향을 "쓸모없다"며 버렸다. 그 이유는 0을 '
            '건너뛰지 않는 경우에만 맞는 이유였다. 0을 건너뛰면 오히려 이쪽이 싸다는 것이 이 연구의 첫 '
            '번째 발견이다.', 'small'),
          Spacer(1, 10)]

    # ----------------------------------------------------------- 5. room
    s += [P('5. 칩 하나로 여섯 층 전부', 'h1'),
          P('CNN의 여섯 층은 크기가 제각각이다. 첫 층은 한 번에 숫자 27개를 보고, 마지막 층은 1,152개를 '
            '본다. 층마다 칩을 새로 만들면(재합성 40분) 쓸 수가 없다.'),
          P('그래서 <b>제일 큰 층에 맞춰 방을 크게 지어 두고</b>, 층마다 "이번엔 몇 칸 쓸 거야"를 '
            '레지스터 두 개로 알려준다. 칩 하나로 여섯 층을 전부 돌린다.'),
          img(figs['room'], width=W*0.92),
          P(f'대신 대가가 있다. 방을 크게 지었으니 칩의 기억 창고(블록 RAM)를 '
            f'<b>{S["pct"]["bram"]:.0%}</b> 쓴다. 레고는 {S["pct"]["lut"]:.0%}만 쓰는데 창고는 절반이다. '
            '"칩 하나로 전부"의 값이 이것이다.', 'body'),
          Spacer(1, 8)]

    # ----------------------------------------------------------- 6. results
    fig9 = FIG/'fig9_classified.png'
    s += [P('6. 결과', 'h1'),
          table([['무엇', '결과'],
                 ['칩이 낸 계산 답', f'{C["outputs_compared"]:,}개'],
                 ['그중 정답과 다른 것', '<b>0개</b>'],
                 ['사진 알아맞히기', f'{C["images"]}장 중 {C["board_correct"]}장 ({C["board_accuracy"]:.1%})'],
                 ['원래(소수점) 인공지능', f'{C["float_accuracy"]:.2%}'],
                 ['사진 한 장에 걸린 시간', f'{C["ms_per_image"]:.2f} ms (초당 {C["fps"]:.1f}장)'],
                 ['일꾼 64명이 일한 비율', f'{C["utilisation"]:.0%}'],
                 ['칩에서 쓴 레고 / 창고 / 전용 계산기',
                  f'{S["pct"]["lut"]:.0%} / {S["pct"]["bram"]:.0%} / {S["dsp"]}개']],
                [W*0.45, W*0.55]),
          Spacer(1, 8)]
    if fig9.exists():
        s += [img(fig9), P('칩이 붙인 이름표. 주황 테두리는 틀린 것이고 "말한 것 / 실제"가 함께 적혀 '
                            '있다. 틀린 것도 개↔고양이처럼 사람도 헷갈릴 만한 짝이다.', 'small')]
    else:
        s += [callout('여기에 <b>fig9_classified.png</b>(칩이 사진에 붙인 이름표)가 들어간다. 보드를 '
                      '돌린 컴퓨터에서 <font name="KRB">python paper/explainer/make_explainer.py</font>를 '
                      '다시 실행하면 자동으로 들어간다.', bg='#f5f5f5', edge=MUTED)]
    s += [Spacer(1, 6),
          callout('<b>"정말 칩에서 돌았나?"</b> 정확도만으로는 증명이 안 된다(칩이 정답과 똑같았으니 '
                  '칩을 건너뛰어도 같은 정확도가 나온다). 증거는 칩 스스로 센 박자 수다. 이 수는 컴퓨터가 '
                  '줄 수 없는 값인데, 미리 계산해 둔 예측과 1% 차이로 맞았고, 두 번 돌려도 한 자리도 '
                  '안 틀리고 같았다.'),
          Spacer(1, 12)]

    # ----------------------------------------------------------- 7. funnel
    s += [KeepTogether([P('7. 뜻밖의 발견: 입구가 좁다', 'h1'),
          P('일꾼을 늘리면 더 빨라질까? 계산해 보니 <b>아니었다.</b> 우리 계산기는 숫자를 '
            '<b>한 박자에 하나씩만</b> 받는다. 깔때기 입구가 좁은 것과 같다.'),
          img(figs['funnelpic'])]),
          P('그래서 한 번에 숫자 288개를 보는 층은 아무리 일꾼이 많아도 최소 288박자가 걸린다. 이게 '
            '"입구 한계"다. 칩을 돌려 보니 모든 층이 이 한계에 딱 붙어 있었다.'),
          img(figs['funnel'], width=W*0.92),
          P(f'사진 한 장 전체로는 실제 {C["cycles_per_image"]:,.0f}박자, 입구 한계 {floor:,}박자로 '
            f'<b>1.2%</b>밖에 차이가 안 난다. 그리고 이 한계값은 <b>칩을 돌리기 전에</b> 계산해서 적어 둔 '
            '값이다. 예측이 맞았다는 뜻이다. (conv1만 18% 높은 건 창이 27칸으로 너무 작아서, 창 사이 '
            '준비 시간 몇 박자가 크게 보이기 때문이다.)'),
          callout('<b>이게 이 연구의 가장 중요한 발견이다.</b> 이 크기의 CNN을 이 크기의 칩에서 돌리면 '
                  '문제는 일꾼(곱셈기) 수가 아니라 입구다. 일꾼을 두 배로 늘려도 5%만 빨라진다. 더 빨라지고 '
                  '싶으면 입구를 넓혀야 한다. 4장의 "Channel이냐 Bank냐"도 이 네트워크에서는 입구 때문에 '
                  '차이가 거의 안 난다 — 우리 결과의 적용 범위를 우리가 먼저 말해 두는 것이다.',
                  bg='#fbf1ea', edge=VERM),
          PageBreak()]

    # ----------------------------------------------------------- 8. honest
    s += [P('8. 솔직하게 말해야 할 것', 'h1'),
          P('논문에서 이걸 숨기면 심사위원이 찾아낸다. 먼저 말하면 신뢰를 얻는다.'),
          table([['한계', '설명', '논문에서'],
                 ['박자가 느리다', f'설계는 100 MHz로 돌 수 있게 만들었지만(여유 +0.221 ns), 보드 설정 탓에 '
                  f'{C["clock_mhz"]:.0f} MHz로 돌았다. 시간은 전부 측정한 50 MHz 값이다.', '측정값만 주장'],
                 ['칩이 전부 한 건 아니다', '곱하기·더하기는 전부 칩. 숫자 재배열, 층 사이 크기 조정, 풀링, '
                  '마지막 분류는 PC가 했다.', '분담을 명시'],
                 ['CPU와 비교 안 함', '공정한 비교 대상은 같은 칩 안의 ARM CPU다. ARM 컴파일러가 없어 아직 '
                  '못 쟀다.', '향후 과제로'],
                 ['시험 사진 128장', '정확도 표본이 작다. 다만 칩이 정수 모델과 완전히 같으므로 정확도는 '
                  '모델의 성질이다.', '그렇게 설명'],
                 ['네트워크 하나, 칩 하나', 'CIFAR-10 6층, XC7Z020에서만 측정했다.', '범위를 명시']],
                [W*0.2, W*0.58, W*0.22]),
          PageBreak()]

    # ----------------------------------------------------------- 9. paper
    s += [P('9. 논문은 이렇게 쓰자', 'h1'),
          P('이 논문의 주인공은 "Channel이냐 Bank냐"가 아니라 <b>"DSP 없이 CNN 전체를, 칩 하나로, 틀림 없이 '
            '돌렸고, 그 한계가 어디인지 미리 알아맞혔다"</b>다. 축 비교는 "왜 이런 모양으로 만들었나"의 '
            '근거로 내려간다.'),
          P('논문이 말해야 할 세 문장', 'h2'),
          callout('① DSP를 하나도 쓰지 않고, 형상이 다른 여섯 층을 비트스트림 하나로 돌려, '
                  f'{C["outputs_compared"]:,}개 출력을 오차 없이 재현했다.<br/>'
                  '② 곱셈기 예산이 고정될 때 0을 건너뛰는 가속기에서는 선행 연구가 버린 탭 뱅크 축이 '
                  '출력 채널 축보다 작고(LUT −29%, FF −57%) 빠르다(−4.4%).<br/>'
                  '③ 그러나 이 크기의 네트워크에서는 입력 포트가 한계이며, 실행 전 예측과 1.2% 이내로 '
                  '맞는다 — 설계 전에 어느 쪽이 한계인지 계산할 수 있다.'),
          P('절 구성', 'h2'),
          table([['절', '내용', '상태'],
                 ['I. 서론', '문제(DSP 없음, 네트워크 전체) → 선행 연구의 기각 이유가 희소성에서 무너짐 → '
                  '입구 한계 발견을 앞에', '영문·한글 완료'],
                 ['II. 구조', '작업 단위, 0 건너뛰기, Channel, Bank, 실행 시점 geometry', '한글 완료, 영문 보강'],
                 ['III. 방법', 'CIFAR 양자화, 층별 실행, 등예산 비교, 검증, 합성, 하드웨어', '한글 완료, 영문 새로'],
                 ['IV. 결과 1', '축 비교(설계 근거로 축소)', '완료'],
                 ['V. 결과 2', '네트워크 전체: 정확성, 입구 한계 표, 자원, 처리율, fig9', '한글 완료, 영문 새로'],
                 ['VI. 논의', '결과의 적용 범위(입구 한계), 한계 목록, 다음 할 일', '한글 완료, 영문 새로']],
                [W*0.16, W*0.6, W*0.24]),
          P('남은 일, 중요한 순서대로', 'h2'),
          table([['순서', '할 일', '왜', '비용'],
                 ['1', '영문 II~VI를 한글판 구조로 다시 쓰기', '투고는 영문', '제 작업'],
                 ['2', 'ARM Cortex-A9 기준선 (SD카드 Linux 추천)', '"CPU보다 얼마나?"에 대한 유일한 공정한 답',
                  'SD카드 + 1~2시간'],
                 ['3', 'build_zedboard.tcl에 -max_dsp 0 고정 후 재빌드', 'DSP 0을 "관측"에서 "보장"으로',
                  '40분 + 보드 10분'],
                 ['4', '전력 추정 (Vivado 리포트)', '이미지당 에너지(J) — FPGA가 이기는 축', '빌드 폴더에 있음'],
                 ['5', '100 MHz 재측정 (선택)', '시간 수치를 설계 능력대로', 'git 동기화 후 10분'],
                 ['6', '급유 경로 넓히기 (다음 논문)', '입구를 넓혀야 일꾼이 다시 의미', '새 연구']],
                [W*0.08, W*0.4, W*0.34, W*0.18]),
          P('하지 말아야 할 것', 'h2'),
          P('· 데스크톱 CPU나 느리게 짠 CPU 코드와 비교해서 "몇 배 빠르다"고 쓰지 않기. 아는 심사위원은 바로 '
            '알아본다.<br/>'
            '· 100 MHz에서 151 fps를 "측정했다"고 쓰지 않기. 측정은 50 MHz, 75.5 fps다.<br/>'
            '· 정확도를 "하드웨어가 돌았다는 증거"로 쓰지 않기. 증거는 박자 수와 스톨 카운터다.<br/>'
            '· 85.9% 대 85.7% 차이를 의미 있게 해석하지 않기. 표본(128장 대 512장)이 다를 뿐이다.'),
          P('투고처 (제안)', 'h2'),
          P('국제 학회라면 FPGA 설계 중심의 FPL, FPT(ICFPT) 같은 학회가 이 규모의 하드웨어 측정 논문과 잘 맞는다. '
            '국내라면 대한전자공학회(IEIE) 학술대회·논문지가 한글판을 그대로 쓸 수 있다. 지도교수님과 '
            '정할 부분이니 참고만 하면 된다.', 'small'),
          Spacer(1, 10),
          P(f'모든 수치 출처: paper/figures/data.py · 이 문서 생성: paper/explainer/make_explainer.py', 'small')]

    out = HERE/'EXPLAINER_KO.pdf'

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('KR', 8.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawRightString(A4[0]-18*mm, 10*mm, f'{doc.page}')
        canvas.restoreState()

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                      topMargin=16*mm, bottomMargin=16*mm,
                      title='작은 칩에 그림 알아맞히기 두뇌 넣기').build(
        s, onFirstPage=footer, onLaterPages=footer)
    print(f'wrote {out}  (font: {Path(FONT_REG).name}; fig9 '
          f'{"included" if fig9.exists() else "not found, placeholder shown"})')


if __name__ == '__main__':
    build()
