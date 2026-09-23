# Running a Whole CNN on a Small FPGA Without DSP Blocks

*(working title; alternatives at the end of this file)*

## I. Introduction

A Zynq-7020 has 220 DSP slices, and a design that has already spent them has to
build its multipliers out of lookup tables and flip-flops. That is the situation
this work starts from, and it is not unusual: on a small part the multiplier is
the resource that runs out first, and the convolution is not the only thing
competing for it. The question is then what a convolutional network costs when
every multiplier is made of fabric, and whether a useful one can be run at all.

Running *a layer* is a smaller problem than running *a network*. A network is a
sequence of convolutions whose shapes differ -- in this work from 27 taps and 32
output channels to 1152 and 128 -- and an accelerator whose geometry is fixed at
synthesis serves exactly one of them. The usual answers are to rebuild per
layer, which is not an answer on hardware, or to size everything for the largest
layer and waste the rest. We take a third: the memories are built for the widest
layer, and two registers say how much of them the layer being run actually uses,
so one bitstream covers the whole network.

Within a layer, the design question is where to put a fixed number of
multipliers. A convolution has several independent axes along which work can be
issued in parallel, and for dense convolution the trade-off has been studied
carefully. Ma et al. [1], [2] enumerate the four loops -- the kernel window, the
input channels, the output feature map and the output channels -- and analyse
what unrolling each costs in data reuse, partial-sum storage and memory traffic.
Their analysis is explicit that the choice is made at a fixed number of
multipliers: in one configuration they hold 3136 MAC units constant, note that
two assignments give the same cycle count, and take the one that needs less bus
width and logic. They reject unrolling the kernel loop for two reasons specific
to dense convolution: kernel windows are small, rarely larger than 11x11, so
that axis cannot supply much parallelism, and the kernel size varies from layer
to layer, leaving processing elements idle on the layers that do not match.

Neither reason survives the move to a sparse accelerator. When zero activations
are skipped, the unit of work is not a fixed kernel window but a variable-length
stream of nonzero taps, and the tap index spans the whole receptive field --
1152 positions in the last layer here, not nine. Multipliers can be spread
across that stream by assigning tap *t* statically to bank *t* mod *T* and
reading one tap from each bank every cycle. The banks run in lockstep, so a
window costs as long as its fullest bank rather than the total number of nonzero
taps, and that imbalance is a property of the data. Existing work that banks a
sparse accelerator removes the imbalance rather than paying it: bank-balanced
sparsity [3] and its fine-grained successors [4] prune the weights into a
pattern the hardware prefers. That is available for weight sparsity and not for
activation sparsity, where the nonzero pattern is not known until the image
arrives.

This paper builds the accelerator, quantizes a six-layer CIFAR-10 network to
7-bit unsigned activations and INT8 weights, and runs every convolution of it on
one bitstream on an XC7Z020. The accelerator computes one thing -- bias plus a
sum of products over a window, then ReLU -- so a layer is an im2col on the host
and one pass of the array; requantization, pooling and the classifier are host
arithmetic. Across 128 test images the hardware reproduced the integer model's
14,680,064 outputs without a single differing value.

The measurement that reframes the design question is what the network then costs
in cycles. The accelerator accepts one activation per cycle, so a window cannot
cost less than its tap count however wide the issue engine is. On this network
every layer sits on that floor: 289 cycles per window where the floor is 288,
1153 where it is 1152. The whole network costs 662,051 cycles per image against
a floor of 654,336, which is 1.18% above a bound written down before the run
from a cycle model that reproduces seven measured configurations to within 1.3
cycles per window. At 64 multipliers the array is doing 91% of the arithmetic it
could; the eight-fold larger budget that would be needed to move the floor buys
5%. For a network of this size on a part of this size, the limit is the input
port, not the multipliers -- and knowing that is worth more than another
doubling of the array.

Our contributions are:

1. **A whole quantized CNN on one bitstream, bit-exact.** Six convolutions of
   differing shape run through memories built for the widest, with the layer's
   geometry set at run time over two registers. 14,680,064 outputs across 128
   images, 0 mismatches against an integer reference, with the design's own
   stall counters reading zero so the cycle counts describe the array and not
   the memory path feeding it.

2. **The network is bound by its input port, not by its multipliers.** Every
   layer's measured cost per window sits on the one-activation-per-cycle floor,
   and the whole network lands 1.18% above a floor predicted before the run.
   The array reaches 91% of the arithmetic 64 multipliers can do at the clock
   measured, and the next doubling of multipliers is worth 5%.

3. **A post-route comparison of two axes at an equal budget.** At 64
   multipliers the tap-banking core uses 29% fewer LUTs and 57% fewer flip-flops
   than the output-channel core. The mechanism is visible in the structure: the
   output-channel axis replicates a 32-bit accumulator per channel, while the
   banking axis sums its products in an adder tree and shares one accumulator.
   It is also faster in time, not only smaller -- 5.1% more cycles per window,
   but 1.040 ns of slack against 0.157, so 4.4% less time per window.

4. **The cost per multiplier is not constant, and the axes diverge with
   scale.** Flip-flops scale linearly, at 111 per multiplier against 45. LUTs do
   not: at a small budget the two axes cost about the same (98 against 99), and
   by the largest budget measured the output-channel axis has risen to 134 while
   banking stays near 93.

5. **A measurement of what static bank assignment costs.** Assigning tap *t* to
   bank *t* mod *T* performs no load balancing. On the evaluation layer the
   penalty is 1.16x at *T*=4 and 1.35x at *T*=8, and it is contained in the
   cycle counts reported rather than left as an unmodelled overhead.

We do not claim the equal-multiplier comparison itself as a contribution;
working at a fixed multiplier count is the premise of [1] and [2]. What is new
is that the axis those works reject, for reasons that do not hold under
sparsity, is cheaper per multiplier than the axis they adopt -- by how much --
and that on a network of this size the choice stops mattering before the
multipliers do.

---

## References (working)

[1] Y. Ma, Y. Cao, S. Vrudhula, and J.-s. Seo, "Optimizing Loop Operation and
    Dataflow in FPGA Acceleration of Deep Convolutional Neural Networks," in
    *Proc. ACM/SIGDA Int. Symp. Field-Programmable Gate Arrays (FPGA)*, 2017,
    pp. 45-54.

[2] Y. Ma, Y. Cao, S. Vrudhula, and J.-s. Seo, "Optimizing the Convolution
    Operation to Accelerate Deep Neural Networks on FPGA," *IEEE Trans. Very
    Large Scale Integr. (VLSI) Syst.*, vol. 26, no. 7, pp. 1354-1367, Jul. 2018.

[3] S. Cao, C. Zhang, et al., "Efficient and Effective Sparse LSTM on FPGA with
    Bank-Balanced Sparsity," in *Proc. FPGA*, 2019.

[4] L. Q. Liu and S. D. Brown, "Leveraging Fine-grained Structured Sparsity for
    CNN Inference on Systolic Array Architectures," in *Proc. FPL*, 2021.

---

## Title alternatives

- Running a Whole CNN on a Small FPGA Without DSP Blocks
- One Bitstream, Six Layers: a Sparse CNN Accelerator Bound by Its Input Port
- Where the Multipliers Stop Mattering: a Sparse CNN Accelerator on a Zynq-7020
- Bit-Exact CIFAR-10 Inference on Fabric Multipliers
