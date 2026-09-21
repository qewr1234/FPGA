# Which figures go in the paper, and where

Four pages with about 3,000 words of body text leaves room for roughly four
figures. Eight exist. This is which four earn the space, and what happens to the
rest.

## In the paper

| # | File | Width | Section | Why it earns the space |
|---|---|---|---|---|
| **1** | `fig1_architectures` | full (2 col) | II | The reader cannot follow the cost argument without seeing that v3 replicates accumulators and v4 shares one behind a tree. Text alone does not carry it. |
| **2** | `fig2_iso_multiplier` | 1 col | IV-A | Cycles against multipliers, log-log. The dashed arrow shows the 85.9% comparison reading *across* the axis, and the vertical read at 64 shows the 5.1% one. One picture makes the fair-comparison argument. |
| **3** | `fig7_scaling` | 1 col | IV-B | Cost per multiplier, LUT and FF panels. **This is the contribution.** If only one figure survived, this is it. |
| **4** | `fig8_visual_check` | full (2 col) | IV-F | Software and hardware feature maps side by side with a zero difference. The only figure that shows the thing working on real data rather than summarising numbers. |

Renumber the files to Fig. 1-4 when the manuscript is assembled; the captions in
`CAPTIONS.txt` follow the script names and will need the same renumbering.

## Cut from the paper, kept for the poster

A poster has several times the area of four columns, so none of this is wasted.

| File | Why it is cut | Where it belongs |
|---|---|---|
| `fig3_overlap_timeline` | The double buffering it shows is one sentence in II-C, and it is not what the paper measures. | Poster -- it explains v3 well to someone standing in front of it. |
| `fig4_iso_tradeoff` | The 32-multiplier comparison is a second reading of what Fig. 2 already shows at 64. | Poster, or drop. |
| `fig5_hw_validation` | Section IV-F is already a table, and the table is more precise per square inch than the figure. | Poster -- as a figure it reads better at arm's length than a table does. |
| `fig6_verification_flow` | Good for credibility, but III says the same in a paragraph, and credibility is not worth a column here. | Poster -- this is exactly what a visitor asks about. |

## Assembly notes

- Both full-width figures (1 and 4) should be placed at the top or bottom of a
  page, not mid-column.
- `paperstyle.py` already sets the column widths: 3.5 in for one column, 7.16 in
  for two, which matches IEEE. No rescaling in the word processor -- rescaling
  changes the font size inside the figure and breaks the match with body text.
- Every figure is written as PDF (vector) as well as 600 dpi PNG. **Use the PDF.**
  A rasterised plot at print size is visibly worse and reviewers notice.
- Rebuild everything with `python paper/figures/make_all.py`; fig8 is separate
  because it needs the data a board run leaves behind.

## Naming

The repository calls the cores v1..v4, which are version labels and mean nothing
to a reader or to an audience. The paper names them by the axis they spend
multipliers on:

| Repository | Paper | Spends multipliers on |
|---|---|---|
| `overlapped_window_mac` (v3) | **Channel** | output channels, *P* of them |
| `banked_window_mac` (v4) | **Bank** | tap banks, *P* x *T* |
| `sparse_window_mac` (v1) | Sparse baseline | shown in Fig. 1 only |

`paperstyle.NAME` holds the mapping so a figure cannot drift from the text.
Where a sentence could read the name as an ordinary noun, write "the Channel
core" or "the Bank core"; in tables and legends the bare name is clearer.
