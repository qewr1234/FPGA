"""Boxes and arrows for the block diagrams, so each figure draws them the same way."""
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import paperstyle as ps


def box(ax, x, y, w, h, text, *, fc=ps.FILL, ec=ps.INK2, fontsize=6.4,
        color=ps.INK, lw=0.7, zorder=3, linespacing=1.25, style="round,pad=0.008"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style,
                                facecolor=fc, edgecolor=ec, linewidth=lw, zorder=zorder))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color=color, zorder=zorder + 1, linespacing=linespacing)
    return (x, y, w, h)


def arrow(ax, p0, p1, *, color=ps.INK2, lw=0.8, style="-|>", scale=6, zorder=2,
          connectionstyle=None, linestyle="-"):
    kw = dict(arrowstyle=style, mutation_scale=scale, color=color,
              linewidth=lw, zorder=zorder, shrinkA=1, shrinkB=1, linestyle=linestyle)
    if connectionstyle:
        kw["connectionstyle"] = connectionstyle
    ax.add_patch(FancyArrowPatch(p0, p1, **kw))


def right(b):
    x, y, w, h = b
    return (x + w, y + h / 2)


def left(b):
    x, y, w, h = b
    return (x, y + h / 2)


def top(b):
    x, y, w, h = b
    return (x + w / 2, y + h)


def bottom(b):
    x, y, w, h = b
    return (x + w / 2, y)


def blank(ax, xlim=(0, 1), ylim=(0, 1)):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_aspect("auto")
