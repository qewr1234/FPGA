"""Every measured number the paper figures draw, in one place.

Each entry names where it came from, so a figure can never quietly drift from the
evidence in the repository. Nothing here is estimated or rounded for effect.

Sources
  verification/included_run/summary.json   cycle counts per configuration
  build/ooc_*/<core>/routed_timing.rpt     WNS, from which Fmax = 1000 / (10 - WNS)
  build/ooc_*/<core>/routed_utilization.rpt   LUT / FF / BRAM
  xsdb run on XC7Z020-CLG484, 2026-09-20   the hardware measurement
"""

# ---------------------------------------------------------------- workload ----
K = 576                 # activations per window
COUT = 128              # output channels
FRAMES = 512
NWINDOWS = 1024         # mode_seq = 2 alternates dense/sparse, so 2 x FRAMES
MACS_PER_WINDOW = K * COUT          # 73,728
RESULT_WORDS = NWINDOWS * COUT      # 131,072

# ------------------------------------------------- cycles per configuration ----
# (multipliers, cycles/window, total cycles, label)
# v3 spends P multipliers; v4 spends P x T.
V3_POINTS = [
    (8,   7230.6, 7404123, "P=8"),
    (32,  1808.1, 1851494, "P=32"),
    (64,   910.7,  932604, "P=64"),
    (128,  577.3,  591194, "P=128"),
]

V4_POINTS = [
    (32,  1910.7, 1956540, "P=8, T=4"),
    (64,  1019.6, 1044037, "P=8, T=8"),
    (64,   956.8,  979737, "P=16, T=4"),
]

# The comparison originally reported, and what makes it unfair: it reads across
# the x axis, from an 8-multiplier core to a 64-multiplier one.
UNFAIR_FROM = (8, 7230.6)     # v3 P=8
UNFAIR_TO = (64, 1019.6)      # v4 P=8, T=8
UNFAIR_PCT = 85.9             # (7230.6 - 1019.6) / 7230.6

# Read vertically at 64 multipliers instead.
FAIR_V3 = (64, 910.7)         # v3 P=64
FAIR_V4 = (64, 956.8)         # v4 P=16, T=4
FAIR_PCT = 5.1                # v4 costs this much more time at the same budget

# ------------------------------------------------- synthesis, 32 multipliers ---
# Vivado out-of-context, xc7z020clg484-1, 10 ns constraint, I/O delays applied.
# Read from the hierarchical utilization reports, top row, 2026-09-20:
#   build/ooc_1789904889_7964/overlapped_window_mac/routed_utilization.rpt
#   build/ooc_1789905694_7964/banked_window_mac/routed_utilization.rpt
#
# Both designs report DSP Blocks = 0, so all 32 multipliers are built from
# fabric in both. That is what makes the LUT comparison mean something: the two
# multiplier arrays are the same size and the same arithmetic, so their cost
# cancels out of the difference, and what is left is the rest of the datapath.
ISO32 = {
    "v3": dict(label="v3  P=32, T=1", mult=32, parallel=32, cycles_per_window=1808.1,
               wns_ns=0.970, fmax_mhz=110.74, us_per_window=16.33,
               lut=4532, logic_lut=3828, lutram=704, ff=3674,
               bram36=33, bram18=0, dsp=0),
    "v4": dict(label="v4  P=8, T=4", mult=32, parallel=8, cycles_per_window=1910.7,
               wns_ns=0.961, fmax_mhz=110.63, us_per_window=17.27,
               lut=3159, logic_lut=2983, lutram=176, ff=1656,
               bram36=32, bram18=4, dsp=0),
}

# Fitting "resource = fixed + per_lane x P" through those two points. The two
# designs spend the same 32 multipliers but differ 4x in P, so anything that
# tracks P shows up here and anything that tracks P x T does not.
#
#   LUTRAM   704/32 = 22.0 per lane      176/8 = 22.0 per lane   -- exactly equal
#   FF       983 fixed + 84.1 per lane   (DEPTH x 32 = 64 result bits + pipeline)
#   LogicLUT 2701 fixed + 35.2 per lane  (output mux and per-lane control)
#   TotalLUT 2701 fixed + 57.2 per lane  = 35.2 + 22.0, which checks against itself
def per_lane(field):
    a, b = ISO32["v3"], ISO32["v4"]
    slope = (a[field] - b[field]) / (a["parallel"] - b["parallel"])
    fixed = b[field] - slope * b["parallel"]
    return fixed, slope

# ------------------------------------------------------ hardware measurement ---
# v3 P=8, DEPTH=2, 100 MHz on XC7Z020-CLG484. Bitstream WNS +0.919 ns, 0 errors.
HW = dict(
    config="v3  P=8, DEPTH=2",
    clock_mhz=100,
    bitstream_wns_ns=0.919,
    simulated_cycles=7404123,
    measured_cycles=7404123,
    windows_expected=NWINDOWS,
    windows_done=1024,
    results_expected=RESULT_WORDS,
    results_produced=131072,
    mismatches=0,
    in_stall=0,
    out_stall=0,
)
HW["us_per_window"] = HW["measured_cycles"] / HW["clock_mhz"] / NWINDOWS

# ------------------------------------------------------------- verification ---
VERIF = dict(
    configurations=167,
    outputs_compared=3447344,
    mismatches=0,
    cycle_rows=30992,
    wrapper_cases=28,
    wrapper_cycle_overhead=0,
)
