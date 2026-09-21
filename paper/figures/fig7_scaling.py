"""Figure 7 -- what a multiplier costs, depending on which axis buys it.

Every point here reports zero DSP blocks, so all multipliers are in fabric and
the LUT counts are comparable with each other. The banked core has three
configurations and the overlapped core two; both are drawn as they are, with no
line extended past the data.

The slopes are the result: an added multiplier costs less when it arrives as a
bank than when it arrives as another output lane, because the output datapath
is sized by P and not by P x T.

Caption to place under this figure:
  Fig. 7. Post-route cost against multiplier budget, Vivado out-of-context,
  xc7z020clg484-1, 10 ns, all multipliers in fabric (0 DSP blocks in every run).
  Repeating a configuration moved the LUT count by at most 2 and left the
  flip-flop count unchanged.
"""
import matplotlib.pyplot as plt

import data
import paperstyle as ps

ps.use_paper_style()

fig, axes = plt.subplots(1, 2, figsize=(ps.COL_W, 2.05))

for ax, field, title in ((axes[0], "lut", "LUTs"), (axes[1], "ff", "Flip-flops")):
    for core, style in (("v3", ps.V3), ("v4", ps.V4)):
        pts = data.points(core, field)
        ax.plot([m for m, _, _ in pts], [v for _, _, v in pts], **style)
        slope = data.per_multiplier(core, field)
        # Anchored in axes fractions so the labels sit beside their own line
        # instead of colliding with the panel title at the top of the frame.
        ax.annotate(f"{slope:.0f} per mult", (0.42, 0.74) if core == "v3" else (0.56, 0.24),
                    xycoords="axes fraction", ha="left" if core == "v3" else "left",
                    fontsize=6.2, color=style["color"])
    ax.set_xscale("log", base=2)
    ax.set_xticks([8, 16, 32])
    ax.set_xticklabels(["8", "16", "32"])
    ax.set_xlim(6.5, 44)
    ax.set_ylim(0, None)
    ax.set_title(title, fontsize=7, color=ps.INK, pad=3)
    ax.set_xlabel("Multipliers spent", fontsize=7)
    ps.recessive_axes(ax, grid_axis="y")
    ax.tick_params(labelsize=6.5)

axes[0].legend(loc="upper left", fontsize=6.2, bbox_to_anchor=(-0.02, 1.02))
fig.subplots_adjust(wspace=0.35)
ps.save(fig, "fig7_scaling")
