# Paper figures

Six figures for the 4-page paper, in English, generated from the measurements in
the repository. Two files come out of each: `.pdf` (vector, for the paper) and
`.png` (600 dpi, for slides and the poster).

```
python make_all.py          # all six
python fig2_iso_multiplier.py   # just one
```

Needs `matplotlib` and `numpy`. Nothing else.

## What each one is for

| Figure | Width | Shows | Worth the space? |
|---|---|---|---|
| `fig1_architectures` | full | the three datapaths side by side | **yes** — the reader needs to see what is being compared |
| `fig2_iso_multiplier` | 1 col | cycles/window vs multipliers, with the unfair and the fair comparison | **yes — this is the paper** |
| `fig3_overlap_timeline` | 1 col | why double buffering removes the idle gap | optional; strong on a poster, cuttable in the paper |
| `fig4_iso_tradeoff` | 1 col | time, LUT and FF at 32 multipliers | **yes** — the trade-off in one look |
| `fig5_hw_validation` | 1 col | measured cycles equal simulated; stall counters zero | **yes** — the evidence for the hardware claim |
| `fig6_verification_flow` | full | the check applied at each stage | optional; good on a poster, cuttable in the paper |
| `fig7_scaling` | 1 col | LUTs and flip-flops against multiplier budget, per architecture | **yes** — it is the mechanism, not just the outcome |

For a four-page two-column paper, three or four figures is usually the limit.
The smallest set that still tells the whole story is **Fig. 1, 2, 5 and 7**. Fig. 7
subsumes Fig. 4: it shows the same trade-off and why it happens.

## Numbers

Every value is in `data.py`, with a comment naming the file it came from. No
figure holds its own copy, so a figure cannot disagree with the text.

Not represented here, because it has not been measured: the iso-multiplier pair
(v3 `P=64` against v4 `P=16, T=4`) was compared in simulation and synthesis, but
only v3 `P=8` has been run on the board. Fig. 5 says so by naming its
configuration.

## Design choices

- **Colour**: Okabe-Ito blue `#0072B2` and vermillion `#D55E00`. The pair clears
  the colour-vision separation check (worst adjacent dE 11.0 under deuteranopia,
  25.8 with normal vision) and both reach 3:1 against white.
- **Not colour alone**: every series also carries its own marker and dash
  pattern, so the figures still read when the proceedings are printed in black
  and white.
- **Type**: serif at 8 pt and below, to sit with the body text instead of
  shouting over it. Fonts are embedded as TrueType, not Type 3, which some
  submission systems reject.
- **Bars start at zero.** Fig. 2's inset shows a 5.1% difference as a 5.1%
  difference; it would look more dramatic on a cropped axis and would be a lie.

## Captions

Each script's docstring ends with the caption to place under that figure. They
are written to be read without the body text, which is how a poster is read.

## fig8_visual_check.py (not in make_all.py)

It is left out of the runner on purpose: it needs data that only a board run
produces, so including it would make `make_all.py` report a failure on every
ordinary rebuild.

The probe in `data/*.wpr` holds 64 windows per image taken from scattered
positions, so its outputs do not form a picture. To get a feature map:

    python scripts/export_featuremap.py --image <img> --size 32
    # run scripts/run_board_xsdb.tcl -- it reads the geometry from featuremap.json
    python paper/figures/fig8_visual_check.py

The repository ships no images; `--list` prints the names and hashes of the ones
the probe was built from. Any photograph works -- the figure shows hardware and
software agreeing, not a reproduction of that probe.

The board script already writes `build/board/results.bin`, so nothing else has
to change to get the hardware panel.

## fig8_visual_check_PREVIEW.png

A screenshot, kept only so the assembled draft can be read whole from any
checkout. **It is not the figure and must not go into the paper** -- it is a
rasterised capture at screen resolution.

The real figure needs `build/board/gold.bin`, `results.bin` and
`featuremap.json`, which a board run leaves behind and which are not committed.
On the machine that has them:

    python paper/figures/fig8_visual_check.py --channel 125

That writes the PDF the paper uses. Commit `fig8_visual_check.pdf`,
`fig8_visual_check.png` and `build/board/featuremap.json` (the last needs
`git add -f`, since `build/` is ignored), then delete this preview.
