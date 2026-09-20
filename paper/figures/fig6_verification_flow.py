"""Figure 6 -- the evidence behind each stage.

Every stage of the flow carries the check that was applied to it, so a number
quoted later can be traced back to the thing that produced it. Two independent
references are used at the RTL stage: an integer model for the values and a
separately written cycle model for the timing, because a change can be correct
and slower at the same time.

Caption to place under this figure:
  Fig. 6. Verification flow. Each stage lists the check applied to it. The cycle
  model is written independently of the RTL, so output correctness and processing
  latency are verified against separate references.
"""
import matplotlib.pyplot as plt

import data
import paperstyle as ps
import schematic as sc

ps.use_paper_style()
v = data.VERIF
hw = data.HW

fig, ax = plt.subplots(figsize=(ps.FULL_W, 1.7))
sc.blank(ax)

stages = [
    ("real VGG11\nactivations", None),
    ("RTL core\n(4 variants)",
     f"vs integer reference\n{v['outputs_compared']:,} outputs\n{v['mismatches']} mismatches\n\n"
     f"vs independent cycle model\n{v['cycle_rows']:,} rows agree"),
    ("AXI4-Stream\nwrapper",
     f"{v['wrapper_cases']} cases,\ncycle overhead {v['wrapper_cycle_overhead']}"),
    ("bitstream\n100 MHz",
     f"WNS $+${hw['bitstream_wns_ns']:.3f} ns,\n0 errors"),
    ("XC7Z020\nboard",
     f"{hw['results_produced']:,} outputs,\n{hw['mismatches']} mismatches\n"
     f"cycles identical\nto simulation"),
]

n = len(stages)
w, gap = 0.158, 0.047
x0 = 0.012
boxes = []
for i, (name, _) in enumerate(stages):
    x = x0 + i * (w + gap)
    fc = "#dce7ef" if i == n - 1 else ps.FILL
    ec = ps.BLUE if i == n - 1 else ps.INK2
    boxes.append(sc.box(ax, x, 0.66, w, 0.22, name, fc=fc, ec=ec, fontsize=6.3))

for a, b in zip(boxes, boxes[1:]):
    sc.arrow(ax, sc.right(a), sc.left(b))

for b, (_, check) in zip(boxes, stages):
    if not check:
        continue
    cx = b[0] + b[2] / 2
    sc.arrow(ax, (cx, 0.64), (cx, 0.575), color=ps.MUTED, scale=5, lw=0.7)
    ax.text(cx, 0.53, check, ha="center", va="top", fontsize=5.7,
            color=ps.INK2, linespacing=1.45)

ax.text(0.012, 0.955, "every stage carries the check that was applied to it",
        fontsize=6.4, color=ps.INK)
ps.save(fig, "fig6_verification_flow")
