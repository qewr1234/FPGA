"""Figure 3 -- where the overlapped datapath's cycles come from.

A schedule, not a measurement: it shows the mechanism behind the v1-to-v3
difference. The baseline alternates loading a window and computing it, so the
multipliers idle during every load. Double buffering moves the load underneath
the compute, and the idle gaps close.

Caption to place under this figure:
  Fig. 3. Window schedule. (a) the sparse baseline alternates load and compute,
  leaving the MAC array idle during each load; (b) with two window buffers the
  load of window n+1 runs underneath the compute of window n.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import paperstyle as ps

ps.use_paper_style()

LOAD = "#c8d8e4"
COMP = ps.BLUE
IDLE = "#f0e3d8"

fig, axes = plt.subplots(2, 1, figsize=(ps.COL_W, 2.05), sharex=True)

t_load, t_comp = 1.0, 2.2


def bar(ax, row, x, w, color, label=None, text_color=ps.INK):
    ax.add_patch(Rectangle((x, row - 0.30), w, 0.60, facecolor=color,
                           edgecolor=ps.SURFACE, linewidth=1.2, zorder=3))
    if label:
        ax.text(x + w / 2, row, label, ha="center", va="center",
                fontsize=5.8, color=text_color, zorder=4)


# ---------------------------------------------------------------- baseline ---
ax = axes[0]
t = 0.0
for n in range(3):
    bar(ax, 1, t, t_load, LOAD, f"load $n{'' if n == 0 else f'+{n}'}$")
    bar(ax, 0, t, t_load, IDLE, "idle", text_color=ps.VERM)
    t += t_load
    bar(ax, 0, t, t_comp, COMP, f"compute $n{'' if n == 0 else f'+{n}'}$",
        text_color=ps.SURFACE)
    t += t_comp
ax.set_title("(a)  sparse baseline: load and compute alternate",
             fontsize=6.8, color=ps.INK, pad=3, loc="left")

# ------------------------------------------------------------- overlapped ---
ax = axes[1]
t = 0.0
bar(ax, 1, 0.0, t_load, LOAD, "load $n$")
for n in range(3):
    bar(ax, 0, t_load + n * t_comp, t_comp,
        COMP, f"compute $n{'' if n == 0 else f'+{n}'}$", text_color=ps.SURFACE)
    bar(ax, 1, t_load + n * t_comp, t_comp, LOAD, f"load $n+{n+1}$")
ax.set_title("(b)  overlapped: the next load runs under the current compute",
             fontsize=6.8, color=ps.INK, pad=3, loc="left")
ax.annotate("no idle gap", xy=(t_load + t_comp, 0), xytext=(t_load + t_comp, -0.95),
            ha="center", fontsize=6, color=ps.BLUE,
            arrowprops=dict(arrowstyle="-|>", mutation_scale=5,
                            color=ps.BLUE, linewidth=0.7))

for ax in axes:
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["MAC array", "window buffer"], fontsize=6.2)
    ax.set_ylim(-1.15, 1.6)
    ax.set_xlim(-0.05, 3 * (t_load + t_comp) + 0.05)
    ax.set_xticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(ps.MUTED)
    ax.tick_params(axis="y", length=0, colors=ps.INK2)

axes[1].set_xlabel("time $\\rightarrow$", fontsize=6.8, labelpad=1)
fig.subplots_adjust(hspace=0.55)
ps.save(fig, "fig3_overlap_timeline")
