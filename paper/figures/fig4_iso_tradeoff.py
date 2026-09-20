"""Figure 4 -- what the banked datapath buys at a fixed multiplier budget.

Three separate panels rather than one normalised chart: the quantities have
different units and a shared axis would misrepresent them. Read together they say
the banked core is not faster, it is smaller.

Caption to place under this figure:
  Fig. 4. Both configurations spend 32 multipliers. Post-route results, Vivado
  out-of-context, xc7z020clg484-1, 10 ns constraint with I/O delays applied.
  Time per window uses each core's own Fmax.
"""
import matplotlib.pyplot as plt

import data
import paperstyle as ps

ps.use_paper_style()

v3, v4 = data.ISO32["v3"], data.ISO32["v4"]
panels = [
    ("Time per window", "$\\mu$s", v3["us_per_window"], v4["us_per_window"], "{:.2f}"),
    ("LUT", "", v3["lut"], v4["lut"], "{:,.0f}"),
    ("Flip-flops", "", v3["ff"], v4["ff"], "{:,.0f}"),
]

fig, axes = plt.subplots(1, 3, figsize=(ps.COL_W, 1.95))

for ax, (title, unit, a, b, fmt) in zip(axes, panels):
    ax.bar([0], [a], width=0.6, color=ps.BLUE, zorder=3)
    ax.bar([1], [b], width=0.6, color=ps.VERM, zorder=3)
    for i, v in enumerate((a, b)):
        ax.annotate(fmt.format(v), (i, v), textcoords="offset points",
                    xytext=(0, 2.5), ha="center", fontsize=6, color=ps.INK)
    delta = (b - a) / a * 100
    ax.set_title(f"{title}{'  [' + unit + ']' if unit else ''}\n"
                 f"v4 {'$+$' if delta > 0 else '$-$'}{abs(delta):.1f}%",
                 fontsize=6.6, color=ps.INK, pad=3, linespacing=1.35)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["v3", "v4"], fontsize=6.5)
    ax.set_ylim(0, max(a, b) * 1.28)
    ax.set_yticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(ps.MUTED)
    ax.tick_params(axis="x", length=0, pad=2, colors=ps.INK2)

fig.text(0.5, -0.11, f"32 multipliers each:  v3 $P\\!=\\!32$   vs   v4 $P\\!=\\!8, T\\!=\\!4$",
         ha="center", fontsize=6.4, color=ps.INK2)
fig.subplots_adjust(wspace=0.45)
ps.save(fig, "fig4_iso_tradeoff")
