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
# ---------------------------------------- post-route utilisation, every run ----
# Top row of each hierarchical utilisation report, xc7z020clg484-1, 2026-09-20.
# (core, P, T) -> dict. "mult" is P*T for the banked core and P for the others.
UTIL = {
    ("v1 sparse",      2, 1): dict(lut=744,  logic=440,  lutram=304, ff=224,  rb36=32, rb18=0, dsp=2),
    ("v2 continuous",  2, 1): dict(lut=874,  logic=482,  lutram=392, ff=390,  rb36=32, rb18=0, dsp=2),
    ("v3 overlapped",  2, 1): dict(lut=989,  logic=469,  lutram=520, ff=355,  rb36=32, rb18=0, dsp=2),
    ("v4 banked",      2, 4): dict(lut=1003, logic=915,  lutram=88,  ff=605,  rb36=32, rb18=4, dsp=0),
    ("v3 overlapped", 32, 1): dict(lut=4532, logic=3828, lutram=704, ff=3674, rb36=33, rb18=0, dsp=0),
    ("v4 banked",      8, 4): dict(lut=3159, logic=2983, lutram=176, ff=1656, rb36=32, rb18=4, dsp=0),
}

# Three separate P=32 runs of the overlapped core gave 4535, 4535 and 4532 LUTs,
# a spread of 3 LUTs (0.07%), so run-to-run variation is not what any of the
# differences below are made of.
P32_REPEATS_LUT = (4535, 4535, 4532)

# Two caveats that have to travel with these numbers.
#
# 1. DSP inference is not consistent across the set. At P=2 the three
#    non-banked cores each infer 2 DSP blocks, one per lane, while the banked
#    core infers none. At the comparison point both report zero, so that one
#    comparison is clean -- but the set as a whole is not, and a paper would
#    have to pin this down (USE_DSP attribute, or -max_dsp) before reading
#    anything into LUT counts across configurations.
#
# 2. Each architecture has been synthesised at exactly two values of P. A line
#    through two points is not a measured law. The per-multiplier figures below
#    are what those two configurations cost, not a verified scaling rule; a
#    third value of P for each would be needed to claim one.
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


def per_multiplier(core_small, core_big, field):
    """Cost per added multiplier between an architecture's own two runs."""
    (na, pa, ta), (nb, pb, tb) = core_small, core_big
    a, b = UTIL[core_small], UTIL[core_big]
    return (b[field] - a[field]) / (pb * tb - pa * ta)


V3_SMALL, V3_BIG = ("v3 overlapped", 2, 1), ("v3 overlapped", 32, 1)
V4_SMALL, V4_BIG = ("v4 banked", 2, 4), ("v4 banked", 8, 4)

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
