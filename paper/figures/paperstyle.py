"""Shared look for every figure in the paper.

Sized and styled for a two-column IEEE-style page: 3.5 in for a single-column
figure, 7.16 in across both. Type is serif at 8 pt so a figure's labels match the
body text rather than shouting over it.

Colour is Okabe-Ito blue and vermillion, which clear the CVD separation check
(worst adjacent pair dE 11.0 deuteranopia, 25.8 normal vision). Every series also
carries its own marker and dash pattern, so the figures survive being printed in
black and white -- identity is never colour alone.

Each figure is written twice: a vector PDF to place in the paper, and a 600 dpi
PNG for slides and the poster.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --------------------------------------------------------------- geometry ----
COL_W = 3.5       # inches, one column of a two-column page
FULL_W = 7.16     # inches, both columns

# ----------------------------------------------------------------- colour ----
BLUE = "#0072B2"      # Channel  (v3 overlapped_window_mac)
VERM = "#D55E00"      # Bank     (v4 banked_window_mac)

# Display names. The repository calls the cores v3 and v4, which means nothing
# to a reader or an audience; the paper names them by the axis they spend
# multipliers on. Defined here so a figure cannot drift from the text.
NAME = {"v3": "Channel", "v4": "Bank"}
GREEN = "#009E73"     # third series where one is needed
INK = "#1a1a1a"       # primary text
INK2 = "#4d4d4d"      # secondary text
MUTED = "#8c8c8c"     # annotations, grid
SURFACE = "#ffffff"
FILL = "#e8eef2"      # recessive block fill in the schematics

# Series get a marker and a dash pattern as well as a hue.
V3 = dict(color=BLUE, marker="o", linestyle="-", label="Channel")
V4 = dict(color=VERM, marker="s", linestyle="--", label="Bank")


def use_paper_style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "axes.edgecolor": INK2,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "lines.linewidth": 1.4,
        "lines.markersize": 4.5,
        "legend.frameon": False,
        "legend.handlelength": 2.2,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "pdf.fonttype": 42,       # embed as TrueType, not Type 3
        "ps.fonttype": 42,
    })


def recessive_axes(ax, grid_axis="y"):
    """Grid and spines that stay behind the data instead of competing with it."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(True, axis=grid_axis, color=MUTED, alpha=0.30, linewidth=0.5)
    ax.set_axisbelow(True)


def save(fig, stem):
    """Write <stem>.pdf for the paper and <stem>.png at 600 dpi for slides."""
    fig.savefig(f"{stem}.pdf", bbox_inches="tight", pad_inches=0.02)
    fig.savefig(f"{stem}.png", bbox_inches="tight", pad_inches=0.02, dpi=600)
    plt.close(fig)
    print(f"  wrote {stem}.pdf and {stem}.png")
