# Addendum to PROTOCOL_2: skew + relabeling (L3) on the board

Written after the PROTOCOL_2 counts (4a93e08: H4–H6 held, L3 ahead of L2 on all
nine networks with C mod 4 = 0) and **before** any L3 board run or L3 board
prediction. It adds runs; it changes nothing in PROTOCOL_2 or its board plan
(`board_prediction_2.json`, 7312a84, and `RUN_W4_LAYOUTS.cmd` stay as they are).

- **Layout:** L3 of B-32 ReLU s1 exactly as in `perms_2.json` (the PROTOCOL_2
  recipe fitted under the skewed bank rule on Set12 01.png), exported with
  `bankperm/export_layout.py --orders` (relabeling folded into the producers,
  then the skew order on the inputs of conv2..conv9). Function preservation is
  checked before any run: identical denoised PNG and every layer's accumulators
  equal up to the column order on Set12 05.png and BSD68 test001.png in the
  board driver's emulation, and the streamed config and windows with the fake
  xsdb.
- **Runs:** the same W = 4 bitstream (the earlier canary's SHA-256), `--w4 --mode 1
  --fclk 50`, Set12 05.png, 06.png, 07.png, 08.png, one run each, in their own
  folder (`denoise/board_runs/q1_layouts3/`).
- **Prediction:** the exact per-layer cycles (count + the `w4_gaps.py`
  fill-and-drain rule; conv1's measured 17) in `bankperm/board_prediction_3.json`,
  committed before the runs. A layer is predicted if CYCLES − IN_STALL equals it
  exactly; every miss is listed.
- **Comparison:** against the Original and Skew runs of the same images from the
  PROTOCOL_2 board runs, and against L3's own counts in `results_2.json`.
