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
# Top row of each hierarchical utilisation report, xc7z020clg484-1, 2026-09-20
# and 2026-09-21. Key: (core, P, T, run) -> resources.
#
# DSP is the gate. Left to the tool, inference varied: at P=2 the three
# non-banked cores each inferred one DSP block per lane while the banked core
# inferred none. A configuration that put two multipliers in DSP blocks is not
# comparable on LUTs with one that put all of them in fabric, so only the
# DSP = 0 rows form a set. The synthesis script now pins this with -max_dsp.
UTIL = [
    # core  P   T  run       LUT  logic  lutram    ff  rb36 rb18 dsp
    ("v1",  2,  1, "a",      744,   440,    304,   224,  32,  0,  2),
    ("v1",  2,  1, "b",      742,   438,    304,   224,  32,  0,  2),
    ("v2",  2,  1, "a",      874,   482,    392,   390,  32,  0,  2),
    ("v2",  2,  1, "b",      876,   484,    392,   390,  32,  0,  2),
    ("v3",  2,  1, "a",      989,   469,    520,   355,  32,  0,  2),
    ("v3",  2,  1, "b",      991,   471,    520,   355,  32,  0,  2),
    ("v3",  8,  1, "a",     1209,  1033,    176,   995,  33,  0,  0),
    ("v3", 32,  1, "a",     4535,  3831,    704,  3674,  33,  0,  0),
    ("v3", 32,  1, "b",     4535,  3831,    704,  3674,  33,  0,  0),
    ("v3", 32,  1, "c",     4532,  3828,    704,  3674,  33,  0,  0),
    ("v4",  2,  4, "a",     1003,   915,     88,   605,  32,  4,  0),
    ("v4",  2,  4, "b",     1004,   916,     88,   605,  32,  4,  0),
    ("v4",  4,  4, "a",     1795,  1707,     88,   953,  32,  4,  0),
    ("v4",  8,  4, "a",     3159,  2983,    176,  1656,  32,  4,  0),
]
FIELDS = ("lut", "logic", "lutram", "ff", "rb36", "rb18", "dsp")

# Repeating a configuration moves the LUT count by at most 2, and three separate
# P=32 runs span 3 LUTs. Flip-flop counts repeat exactly. Nothing below is
# run-to-run noise.
REPEATABILITY_MAX_LUT_DELTA = 3


def rows(core=None, dsp_zero_only=True):
    out = []
    for r in UTIL:
        if core and r[0] != core:
            continue
        if dsp_zero_only and r[-1] != 0:
            continue
        out.append(dict(zip(("core", "P", "T", "run") + FIELDS, r)))
    return out


def points(core, field):
    """(multipliers, value) per configuration, averaged over repeated runs."""
    acc = {}
    for r in rows(core):
        acc.setdefault(r["P"] * r["T"], []).append((r["P"], r[field]))
    return sorted((m, v[0][0], sum(x for _, x in v) / len(v)) for m, v in acc.items())


def per_multiplier(core, field):
    p = points(core, field)
    return (p[-1][2] - p[0][2]) / (p[-1][0] - p[0][0])


# Distributed RAM comes to 22 LUTRAM per output lane at every DSP = 0 point with
# P >= 4, in both architectures: v3 at P=8 and P=32, v4 at P=4 and P=8. It
# tracks P and not P x T, which is the claim this work makes about where the
# area goes. v4 at P=2 floors at 88 rather than 44, so the relation has a floor
# rather than holding everywhere.
LUTRAM_PER_LANE = 22


# The 32-multiplier comparison point, assembled from the rows above so there is
# one copy of each number. Timing comes from the routed timing reports.
def _at(core, mult, field):
    for m, _P, v in points(core, field):
        if m == mult:
            return v
    raise KeyError(f"{core} has no {mult}-multiplier run")


ISO32 = {
    "v3": dict(label="v3  P=32, T=1", mult=32, parallel=32, cycles_per_window=1808.1,
               wns_ns=0.970, fmax_mhz=110.74, us_per_window=16.33,
               lut=_at("v3", 32, "lut"), logic_lut=_at("v3", 32, "logic"),
               lutram=_at("v3", 32, "lutram"), ff=_at("v3", 32, "ff"),
               bram36=33, bram18=0, dsp=0),
    "v4": dict(label="v4  P=8, T=4", mult=32, parallel=8, cycles_per_window=1910.7,
               wns_ns=0.961, fmax_mhz=110.63, us_per_window=17.27,
               lut=_at("v4", 32, "lut"), logic_lut=_at("v4", 32, "logic"),
               lutram=_at("v4", 32, "lutram"), ff=_at("v4", 32, "ff"),
               bram36=32, bram18=4, dsp=0),
}

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
