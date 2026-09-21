## III. Method

### A. Workload

All measurements use one convolution layer, `features.3` of a VGG11 pretrained
on ImageNet: 64 input channels to 128 output channels with a 3x3 kernel, so
*K* = 64 x 3 x 3 = 576 and *COUT* = 128, and 73,728 multiply-accumulates per
window. Activations are quantized to unsigned 8-bit with one scale per layer,
taken as the maximum over a calibration set, and weights to signed 8-bit.
Rounding is nearest, ties to even. Activations reach the accelerator already
rectified by the preceding layer, so the nonzero rate is a property of the data:
0.569 on the evaluation set used here, ranging from 0.106 to 0.979 across tap
positions.

### B. Equal-multiplier comparison

A speed-up measured against a baseline with fewer multipliers says little. Every
comparison in Section IV therefore fixes the number of multipliers and varies
only how they are assigned: v3 at *P* multipliers against v4 at *P* x *T*, with
the pair chosen so the products are equal. This is not a new methodology -- it
is the premise of [1] and [2] -- but it is the condition under which the
resource question has an answer.

### C. Correctness

Values and timing are checked against separate references, so an error in one
cannot hide an error in the other.

Values are checked against an integer oracle written in Python directly from the
definition in Section II-A, independently of the RTL. The oracle also asserts
its own preconditions: every activation within 0..127, every weight within
-128..127, and the worst-case accumulator for every channel inside INT32.

Timing is checked against a cycle model written from the handshake protocol
rather than from the RTL, and compared per window. Deriving the expected cycles
from the design under test would be circular; the model predicts, and the
simulation is required to agree.

Across 167 configurations -- the four cores, values of *P* from 1 to 128, *T*
from 1 to 8, with and without throttled input and output -- 3,447,344 outputs
matched the oracle with no mismatches, and the cycle counts matched the model.
The suite also checks that the wrapper costs nothing: its reported cycle count
must equal the bare core's on the same stream, and the bench fails if it does
not.

### D. Synthesis

Resources are reported after place and route, not after synthesis, from Vivado
2026.1 targeting xc7z020clg484-1 out of context with a 10 ns constraint and
input and output delays applied. Fmax is derived from worst negative slack as
`1000/(10 - WNS)`.

Two decisions matter for comparability.

*DSP inference is disabled* (`-max_dsp 0`). Left to the tool, DSP use varied with
configuration -- two DSPs inferred for one core at *P* = 2 and none for another
at the same point -- which makes the LUT columns of those runs incomparable, as
part of the arithmetic has left the fabric. Forcing every configuration to build
its multipliers from logic puts all points on one axis. This matches the case
the paper is about: a device whose DSPs are already committed.

*Hold checks on the out-of-context boundary are relaxed* with
`set_false_path -hold` on the non-clock inputs and on the outputs. Out of
context, Vivado models those paths without the shared clock tree the real design
has, and reports hold violations on thousands of endpoints that do not exist
once the core is placed in the full design. Setup, which is what the Fmax
comparison depends on, remains fully checked.

Resource figures are read from the hierarchical utilisation report's `(top)`
row, not from the summary table: the two report different quantities, and
"Total LUTs" in the hierarchical report is the one that includes LUTs used as
memory.

### E. Hardware

The design runs on a Zedboard, XC7Z020-CLG484, at 100 MHz, with the core behind
an AXI DMA reaching DDR through the PS high-performance port. The bitstream
closes timing with 0.919 ns of slack.

Weights, activations and the reference outputs are written to DDR over JTAG, the
core is configured and run, and the results are read back and compared on the
host. Because the debugger writes through the processor's caches while the DMA
reads DDR directly, the caches and MMU are disabled before any data is written;
without this the accelerator reads whatever the previous run left in memory, and
every file on the host is still correct.

Two runs are reported. The first streams 1,024 windows sampled from eight
images, alternating dense and sparse mode per window so that the two modes can be
required to agree. The second streams a complete 112x112 feature map -- 12,544
contiguous windows from one image -- so that the output can be shown as a picture
rather than as a count.
