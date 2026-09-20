"""Figure 1 -- the three datapaths that are compared.

All three skip multiplications whose activation is zero. They differ in what they
do with the cycles that skipping frees: (a) spends them waiting for the next
window, (b) hides that wait behind a second buffer, (c) issues several nonzero
taps at once and pays for it in multipliers.

Caption to place under this figure:
  Fig. 1. Window MAC datapaths compared in this work. A window holds K = 576
  activations and produces COUT = 128 outputs. (a) skips zero activations only;
  (b) adds a second window buffer so the next load overlaps the current compute;
  (c) distributes nonzero taps over T banks and sums them, spending P x T
  multipliers instead of P.
"""
import matplotlib.pyplot as plt

import paperstyle as ps
import schematic as sc

ps.use_paper_style()

fig, axes = plt.subplots(1, 3, figsize=(ps.FULL_W, 2.3))
for ax, t in zip(axes, ["(a)  v1  sparse baseline",
                        "(b)  v3  overlapped",
                        "(c)  v4  banked"]):
    sc.blank(ax)
    ax.set_title(t, fontsize=7.5, color=ps.INK, pad=5)

FS = 6.0

# ------------------------------------------------------------------ (a) v1 ---
ax = axes[0]
b_win = sc.box(ax, 0.04, 0.78, 0.38, 0.11, "window buffer", fontsize=FS)
b_scn = sc.box(ax, 0.04, 0.60, 0.38, 0.11, "nonzero scan", fontsize=FS)
b_mac = sc.box(ax, 0.58, 0.60, 0.38, 0.29, "MAC array\n$P$ lanes", fontsize=FS)
b_acc = sc.box(ax, 0.26, 0.34, 0.56, 0.12, "accumulate $+$ bias $+$ ReLU", fontsize=FS)
sc.arrow(ax, sc.bottom(b_win), sc.top(b_scn))
sc.arrow(ax, sc.right(b_scn), sc.left(b_mac))
sc.arrow(ax, sc.bottom(b_mac), (0.77, 0.46))
sc.arrow(ax, sc.bottom(b_acc), (0.54, 0.20))
ax.text(0.50, 0.09, "the next window waits for this one",
        fontsize=FS, color=ps.VERM, ha="center")

# ------------------------------------------------------------------ (b) v3 ---
ax = axes[1]
sc.box(ax, 0.05, 0.78, 0.38, 0.11, "A   compute", fc="#dce7ef", fontsize=FS)
sc.box(ax, 0.05, 0.62, 0.38, 0.11, "B   prefetch", fc=ps.SURFACE, fontsize=FS)
ax.annotate("", xy=(0.025, 0.665), xytext=(0.025, 0.845),
            arrowprops=dict(arrowstyle="<|-|>", mutation_scale=5,
                            color=ps.BLUE, linewidth=0.8))
ax.text(0.05, 0.545, "roles swap every window", fontsize=5.8, color=ps.BLUE)
b_scn = sc.box(ax, 0.05, 0.38, 0.30, 0.11, "nonzero scan", fontsize=FS)
b_mac = sc.box(ax, 0.60, 0.62, 0.36, 0.27, "MAC array\n$P$ lanes", fontsize=FS)
b_acc = sc.box(ax, 0.44, 0.34, 0.54, 0.12, "accum. $+$ bias $+$ ReLU", fontsize=FS)
sc.arrow(ax, sc.right(b_scn), (0.60, 0.70),
         connectionstyle="angle3,angleA=0,angleB=75")
sc.arrow(ax, sc.bottom(b_mac), (0.78, 0.46))
sc.arrow(ax, sc.bottom(b_acc), (0.70, 0.20))
ax.text(0.50, 0.09, "the load hides behind the compute",
        fontsize=FS, color=ps.BLUE, ha="center")

# ------------------------------------------------------------------ (c) v4 ---
ax = axes[2]
b_scn = sc.box(ax, 0.02, 0.80, 0.34, 0.11, "nonzero scan", fontsize=FS)
b_dmx = sc.box(ax, 0.02, 0.62, 0.34, 0.11,
               "bank $=t\\,\\mathrm{mod}\\,T$", fontsize=5.7)
sc.arrow(ax, sc.bottom(b_scn), sc.top(b_dmx))

banks = [sc.box(ax, 0.43, y, 0.21, 0.10, lab, fontsize=5.5)
         for y, lab in [(0.80, "bank 0"), (0.66, "bank 1"), (0.44, "bank $T\\!-\\!1$")]]
ax.text(0.535, 0.585, "$\\vdots$", fontsize=8, ha="center", color=ps.INK2)
for bb in banks:
    sc.arrow(ax, (0.36, 0.675), sc.left(bb),
             connectionstyle="angle3,angleA=0,angleB=70")

b_sum = sc.box(ax, 0.74, 0.58, 0.20, 0.15, "$T$-sum\ntree", fc="#f6e2d6",
               ec=ps.VERM, fontsize=5.5)
for bb in banks:
    sc.arrow(ax, sc.right(bb), sc.left(b_sum), color=ps.VERM,
             connectionstyle="angle3,angleA=0,angleB=75")

b_acc = sc.box(ax, 0.30, 0.26, 0.62, 0.12, "accum. $+$ bias $+$ ReLU", fontsize=FS)
sc.arrow(ax, sc.bottom(b_sum), (0.84, 0.38), color=ps.VERM)
sc.arrow(ax, sc.bottom(b_acc), (0.61, 0.16))
ax.text(0.50, 0.07, "$T$ nonzero taps issued per cycle",
        fontsize=FS, color=ps.VERM, ha="center")
ax.text(0.02, 0.44, "$P\\times T$\nmultipliers", fontsize=6.2, color=ps.VERM,
        va="center", linespacing=1.3)

fig.subplots_adjust(wspace=0.10)
ps.save(fig, "fig1_architectures")
