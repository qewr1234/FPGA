"""Figure 5 -- the hardware run, and why its number is comparable.

Two claims, each with its own row. The cycle count measured on the board is the
count the simulation predicted, exactly. And the core never waited: the stall
counters built into the wrapper read zero, so the figure measures the core rather
than the memory path feeding it.

Caption to place under this figure:
  Fig. 5. v3, P = 8, at 100 MHz on XC7Z020-CLG484 over 1,024 windows.
  All 131,072 outputs matched the integer reference.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import data
import paperstyle as ps

ps.use_paper_style()
hw = data.HW

fig, (ax, axb) = plt.subplots(2, 1, figsize=(ps.COL_W, 1.85),
                              gridspec_kw=dict(height_ratios=[1.0, 0.85]))

# ---- simulated against measured -------------------------------------------
rows = [("simulated", hw["simulated_cycles"], ps.MUTED),
        ("measured on board", hw["measured_cycles"], ps.BLUE)]
for i, (lab, val, col) in enumerate(rows):
    ax.barh(1 - i, val, height=0.52, color=col, zorder=3)
    ax.annotate(f"{val:,}", (val, 1 - i), textcoords="offset points",
                xytext=(4, 0), va="center", fontsize=6.2, color=ps.INK)
ax.set_yticks([0, 1])
ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=6.4)
ax.set_xlim(0, hw["measured_cycles"] * 1.30)
ax.set_xticks([])
ax.set_ylim(-0.55, 1.55)
ax.set_title(f"cycles for {data.NWINDOWS:,} windows   "
             f"($\\Delta = 0$ cycles)", fontsize=6.8, color=ps.INK, pad=3, loc="left")
for s in ("top", "right", "bottom"):
    ax.spines[s].set_visible(False)
ax.spines["left"].set_color(ps.MUTED)
ax.tick_params(axis="y", length=0, colors=ps.INK2)

# ---- where those cycles went ----------------------------------------------
total = hw["measured_cycles"]
active = total - hw["in_stall"] - hw["out_stall"]
axb.add_patch(Rectangle((0, 0.2), active, 0.6, facecolor=ps.BLUE, zorder=3))
axb.text(active / 2, 0.5, "core busy", ha="center", va="center",
         fontsize=6.2, color=ps.SURFACE, zorder=4)
axb.set_xlim(0, total * 1.30)
axb.set_ylim(0, 1.0)
axb.set_xticks([])
axb.set_yticks([])
for s in axb.spines.values():
    s.set_visible(False)
axb.annotate(f"input stall {hw['in_stall']} cycles\n"
             f"output stall {hw['out_stall']} cycles",
             xy=(total, 0.5), xytext=(total * 1.03, 0.5), va="center",
             fontsize=6.2, color=ps.VERM, linespacing=1.4)
axb.set_title("the core never waited, so this is the core and not the DMA",
              fontsize=6.4, color=ps.INK2, pad=2, loc="left")

fig.subplots_adjust(hspace=0.95)
ps.save(fig, "fig5_hw_validation")
