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
    #
    # Only RUNTIME_GEOM = 0 runs. The feature was added to Channel and not to
    # Bank, and it costs 140 LUTs at P = 2, so measuring the comparison on it
    # would have priced a feature only one of the two cores carries. Re-measured
    # 2026-09-22 after making it a compile-time switch, default off.
    ("v3",  2,  1, "a",      992,   472,    520,   363,  32,  0,  0),
    ("v3", 16,  1, "a",     2360,  2008,    352,  1895,  32,  0,  0),
    ("v3", 64,  1, "a",     8812,  7404,   1408,  7248,  32, 64,  0),
    # Bank was never changed, so these stand as measured.
    ("v4",  2,  4, "a",     1003,   915,     88,   605,  32,  4,  0),
    ("v4",  2,  4, "b",     1004,   916,     88,   605,  32,  4,  0),
    ("v4",  4,  4, "a",     1795,  1707,     88,   953,  32,  4,  0),
    ("v4",  8,  4, "a",     3159,  2983,    176,  1656,  32,  4,  0),
    ("v4", 16,  4, "a",     6218,  5866,    352,  3107,  32, 68,  0),
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


# The equal-budget comparison point, assembled from the rows above so there is
# one copy of each number. It reads at 64 multipliers, which is the pair the
# paper discusses and the one both bitstreams were built for. Timing comes from
# the routed timing reports.
def _at(core, mult, field):
    for m, _P, v in points(core, field):
        if m == mult:
            return v
    raise KeyError(f"{core} has no {mult}-multiplier run")


def _fmax(wns_ns, period_ns=10.0):
    """Fmax from worst negative slack on the constrained period."""
    return 1000.0 / (period_ns - wns_ns)


ISO64 = {
    "v3": dict(label="Channel  P=64", mult=64, parallel=64, cycles_per_window=910.7,
               wns_ns=0.157, fmax_mhz=_fmax(0.157),
               us_per_window=910.7 / _fmax(0.157),
               lut=_at("v3", 64, "lut"), logic_lut=_at("v3", 64, "logic"),
               lutram=_at("v3", 64, "lutram"), ff=_at("v3", 64, "ff"),
               bram36=32, bram18=64, dsp=0),
    "v4": dict(label="Bank  P=16, T=4", mult=64, parallel=16, cycles_per_window=956.8,
               wns_ns=1.040, fmax_mhz=_fmax(1.040),
               us_per_window=956.8 / _fmax(1.040),
               lut=_at("v4", 64, "lut"), logic_lut=_at("v4", 64, "logic"),
               lutram=_at("v4", 64, "lutram"), ff=_at("v4", 64, "ff"),
               bram36=32, bram18=68, dsp=0),
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

# ----------------------------------------------- CIFAR-10 network, on board ---
# The whole quantized network run layer by layer on XC7Z020-CLG484, banked
# (Bank) core, P=16 T=4 DEPTH=2, one bitstream built at K<=1152 COUT<=128 with
# runtime geometry, 128 CIFAR-10 test images.
#
# The clock is 50 MHz and that is not a choice: the PS preset available on this
# machine hands the fabric 50 MHz, while the design is routed and meets timing
# at 100 (whole-board WNS +0.221 ns). Every time below is therefore at half the
# frequency the design closed at. Cycle counts do not depend on the clock, so
# they stand on their own; the times do not, and are reported as measured.
#
# Source: build/cifar_run/report.json, run of 2026-09-23.
CIFAR = dict(
    core="Bank  P=16, T=4, DEPTH=2",
    built_k=1152, built_cout=128, runtime_geometry=True,
    clock_mhz=50.0,
    routed_wns_ns=0.221,          # at the 100 MHz constraint, whole board design
    images=128,
    mode="sparse",                # zero activations skipped
    float_accuracy=0.8626,        # the trained network, full 10,000-image test set
    integer_accuracy_512=0.8574,  # the quantized model on 512 images, host
    board_accuracy=0.8594,        # 110 / 128, on hardware
    board_correct=110,
    outputs_compared=14680064,
    mismatches=0,
    in_stall=0, out_stall=0,
    total_cycles=84742543,
    macs_per_image=38633472,
)
CIFAR["cycles_per_image"] = CIFAR["total_cycles"] / CIFAR["images"]
CIFAR["ms_per_image"] = CIFAR["cycles_per_image"] / CIFAR["clock_mhz"] / 1000.0
CIFAR["fps"] = 1000.0 / CIFAR["ms_per_image"]
CIFAR["gmac_per_s"] = CIFAR["macs_per_image"] / (CIFAR["ms_per_image"] / 1000.0) / 1e9
# 64 multipliers, one result each per cycle.
CIFAR["peak_gmac_per_s"] = 64 * CIFAR["clock_mhz"] * 1e6 / 1e9
CIFAR["utilisation"] = CIFAR["gmac_per_s"] / CIFAR["peak_gmac_per_s"]

# Per layer, in order. windows and K are per image; cycles and density are what
# the board reported over the 128-image batch.
#
# "floor" is K: one activation enters the core per cycle, so a window cannot cost
# less however wide the issue engine is. Measured cycles per window sit on that
# floor at every layer, which is the finding -- this network is bound by the
# input port, not by multipliers.
CIFAR_LAYERS = [
    # name    windows    K  COUT  nonzero      cycles  cyc/window
    ("conv1",    1024,   27,   32,  0.951,    4194339,    32.0),
    ("conv2",    1024,  288,   32,  0.586,   37879875,   289.0),
    ("conv3",     256,  288,   64,  0.567,    9470075,   289.0),
    ("conv4",     256,  576,   64,  0.381,   18907283,   577.0),
    ("conv5",      64,  576,  128,  0.351,    4845439,   591.5),
    ("conv6",      64, 1152,  128,  0.125,    9445532,  1153.0),
]
CIFAR_FIELDS = ("name", "windows", "K", "COUT", "nonzero", "cycles", "cycles_per_window")

# Predicted before the run from the cycle model, using the per-layer density
# measured on the host: scripts/cifar_budget.py --report build/cifar_run/report.json.
# The model reproduces all seven configurations measured on the evaluation probe
# to within 1.3 cycles per window, so this was a prediction, not a fit.
CIFAR_PREDICTED_CYCLES_PER_IMAGE = 654336


def cifar_layers():
    return [dict(zip(CIFAR_FIELDS, r)) for r in CIFAR_LAYERS]


def cifar_feed_floor():
    """Cycles per image if every window cost exactly K -- the input port's limit."""
    return sum(w * k for _n, w, k, _c, _d, _cy, _cw in CIFAR_LAYERS)

# ------------------------------------------- the whole system, on the board ---
# (top) row of the hierarchical utilisation report for the bitstream the CIFAR
# network ran on: build/zed_v4_p16_t4_1790095039/reports/routed_utilization.rpt.
#
# This is the WHOLE design -- PS7, AXI DMA, the smartconnect to the HP port, the
# interconnect and the core -- not the core alone, which is what Table I's
# out-of-context numbers are. The two are not comparable and are not compared.
#
# DSP = 0 was not constrained here. build_zedboard.tcl sets no DSP limit; Vivado
# inferred none anyway, presumably judging an 8-bit multiply cheaper in fabric.
# The out-of-context comparison pins it with -max_dsp 0 for comparability; this
# board build did not, so the zero is an observation about this build rather
# than a property guaranteed by the flow.
XC7Z020 = dict(lut=53200, ff=106400, ramb36=140, ramb18=280, dsp=220)

SYSTEM = dict(
    build="zed_v4_p16_t4_1790095039",
    core="Bank  P=16, T=4, DEPTH=2, K<=1152, COUT<=128, runtime geometry",
    lut=11182, logic_lut=10217, lutram=774, srl=191, ff=9372,
    ramb36=68, ramb18=6, dsp=0,
    dsp_constrained=False,
    clock_mhz=50.0, routed_wns_ns=0.221, constraint_ns=10.0,
)
# Block RAM in RAMB18 equivalents: a RAMB36 is two of them.
SYSTEM["ramb18_equiv"] = SYSTEM["ramb36"]*2 + SYSTEM["ramb18"]
SYSTEM["pct"] = dict(
    lut=SYSTEM["lut"]/XC7Z020["lut"],
    ff=SYSTEM["ff"]/XC7Z020["ff"],
    bram=SYSTEM["ramb18_equiv"]/XC7Z020["ramb18"],
    dsp=SYSTEM["dsp"]/XC7Z020["dsp"],
)
