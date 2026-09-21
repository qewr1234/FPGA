"""Figure 2 -- why the headline speedup was an artifact of the comparison.

The one figure the paper rests on. Cycles per window against the number of
multipliers a configuration spends. Both architectures lie on nearly the same
curve, so a speedup quoted between two different x positions measures the budget,
not the design. The inset reads the same data vertically, at one budget, where
the two are within a few percent and the ordering is the other way round.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

import data
import paperstyle as ps

ps.use_paper_style()

fig, ax = plt.subplots(figsize=(ps.COL_W, 3.3))

# ---- v3: one configuration per budget, so a single curve ----
ax.plot([m for m, _, _, _ in data.V3_POINTS],
        [c for _, c, _, _ in data.V3_POINTS], zorder=3, **ps.V3)

# ---- v4: the best configuration at each budget forms the curve ----
best_v4 = {}
for mult, cyc, _, lab in data.V4_POINTS:
    if mult not in best_v4 or cyc < best_v4[mult][0]:
        best_v4[mult] = (cyc, lab)
v4_x = sorted(best_v4)
ax.plot(v4_x, [best_v4[m][0] for m in v4_x], zorder=3, **ps.V4)

# The other 64-multiplier v4 configuration, hollow so it reads as secondary.
for m, c, _, l in data.V4_POINTS:
    if best_v4[m][0] != c:
        ax.plot([m], [c], marker="s", markersize=4.5, markerfacecolor=ps.SURFACE,
                markeredgecolor=ps.VERM, markeredgewidth=1.1,
                linestyle="none", zorder=4)

# ---- the comparison originally reported: it reads across the x axis ----
ax.add_patch(FancyArrowPatch(data.UNFAIR_FROM, data.UNFAIR_TO,
                             arrowstyle="-|>", mutation_scale=7,
                             color=ps.MUTED, linewidth=0.9, linestyle=(0, (4, 2)),
                             shrinkA=7, shrinkB=9, zorder=2))
ax.annotate(f"quoted as $-${data.UNFAIR_PCT:.1f}%,\nbut read across the axis:\n"
            "8 multipliers vs 64",
            xy=(22, 2700), xytext=(9.2, 900), ha="left", va="center",
            fontsize=6.5, color=ps.INK2, linespacing=1.4,
            arrowprops=dict(arrowstyle="-", color=ps.MUTED, linewidth=0.5,
                            shrinkA=3, shrinkB=3,
                            connectionstyle="angle3,angleA=0,angleB=70"))

# ---- selective direct labels, not one on every point ----
for m, c, _, lab in data.V3_POINTS:
    if lab in ("P=8", "P=128"):
        ax.annotate(lab, (m, c), textcoords="offset points",
                    xytext=(5, 5) if lab == "P=8" else (-4, 9),
                    fontsize=6.5, color=ps.BLUE)

ax.set_xscale("log", base=2)
ax.set_yscale("log")
ax.set_xticks([8, 16, 32, 64, 128])
ax.set_xticklabels(["8", "16", "32", "64", "128"])
ax.set_yticks([500, 1000, 2000, 5000, 10000])
ax.set_yticklabels(["500", "1k", "2k", "5k", "10k"])
ax.set_xlim(6.5, 190)
ax.set_ylim(430, 13000)
ax.set_xlabel("Multipliers spent")
ax.set_ylabel("Cycles per window")
ps.recessive_axes(ax, grid_axis="both")
ax.legend(loc="lower left", bbox_to_anchor=(-0.01, -0.02))

# ---- inset: the same data read vertically, at one budget ----
axi = inset_axes(ax, width="46%", height="34%", loc="upper right",
                 bbox_to_anchor=(0.0, -0.06, 1.0, 1.0),
                 bbox_transform=ax.transAxes, borderpad=0.1)
bars = [("Channel\nP=64", data.FAIR_V3[1], ps.BLUE),
        ("Bank\nP=16, T=4", data.FAIR_V4[1], ps.VERM)]
for i, (lab, val, col) in enumerate(bars):
    axi.bar(i, val, width=0.55, color=col, zorder=3)
    axi.annotate(f"{val:.0f}", (i, val), textcoords="offset points",
                 xytext=(0, 2.5), ha="center", fontsize=6, color=ps.INK)
axi.set_xticks([0, 1])
axi.set_xticklabels([b[0] for b in bars], fontsize=6, linespacing=1.2)
axi.set_ylim(0, 1180)
axi.set_yticks([])
axi.set_title(f"at 64 multipliers, v4 costs $+${data.FAIR_PCT:.1f}%",
              fontsize=6.3, color=ps.INK, pad=2.5)
for side in ("top", "right", "left"):
    axi.spines[side].set_visible(False)
axi.spines["bottom"].set_color(ps.MUTED)
axi.tick_params(axis="x", length=0, pad=1.5, colors=ps.INK2)
axi.set_facecolor(ps.SURFACE)

ps.save(fig, "fig2_iso_multiplier")
