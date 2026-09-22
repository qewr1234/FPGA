# Where to Spend the Multipliers in a Sparse CNN Accelerator

*(working title; alternatives at the end of this file)*

## I. Introduction

On a small FPGA the multiplier is the resource that runs out first. A Zynq-7020
offers 220 DSP slices, and a design that has already spent them on other work
must build its multipliers out of logic, where each one costs lookup tables and
flip-flops that the rest of the system also wants. The question such a design
faces is therefore not how many multiply-accumulate units it can afford, but
what to do with the ones it can: a convolution has several independent axes
along which work can be issued in parallel, and a fixed budget of multipliers
can be spread along any of them.

For dense convolution this question has been studied carefully. Ma et al. [1],
[2] enumerate the four loops of a convolution -- the kernel window, the input
channels, the output feature map and the output channels -- and analyse what
unrolling each one costs in data reuse, partial-sum storage and memory traffic.
Their analysis is explicit that the choice is a trade-off at a fixed number of
multipliers: in one configuration they hold 3136 MAC units constant, note that
two assignments of those units give the same cycle count, and choose the one
that needs less bus width and logic. They also reject unrolling the kernel loop,
for two reasons that are specific to dense convolution. Kernel windows are small
-- rarely larger than 11x11 -- so that axis cannot supply much parallelism, and
the kernel size varies from layer to layer, which leaves processing elements
idle on the layers that do not match. Their accelerator therefore unrolls the
feature-map and output-channel loops, and this choice has been widely followed.

Neither reason survives the move to a sparse accelerator. When zero activations
are skipped, the unit of work is no longer a fixed kernel window but a
variable-length stream of nonzero taps, and the tap index spans the whole
receptive field: 576 positions for the layer studied here, not nine. An
accelerator can spread its multipliers across that stream by assigning tap *t*
statically to bank *t* mod *T*, reading one tap from each bank every cycle. This
is a different structure from a dense unroll of the same loops. The banks run in
lockstep, so a window costs as long as its fullest bank rather than the total
number of nonzero taps, and the cost of that imbalance depends on the data
rather than on the architecture. Existing work that banks a sparse accelerator
removes the imbalance instead of paying it: bank-balanced sparsity [3] and its
fine-grained successors [4] prune the weights into a pattern the hardware
prefers, which is available for weight sparsity and not for activation sparsity,
where the nonzero pattern is not known until the image arrives.

What has not been reported, as far as we can determine, is what this axis
actually costs in fabric. The dense analyses measure memory accesses and DSP
utilisation; the sparse accelerators that use banking report whole-design
resource totals for one configuration. Neither answers the question a designer
with a fixed multiplier budget has to answer: per multiplier added, how much
logic does each axis consume, and what does each buy in throughput?

This paper measures that. We implement four window-level MAC cores in
SystemVerilog for one convolution layer of a quantized VGG11, compare the
output-channel axis against the sparse tap-banking axis at an equal number of
multipliers, and report post-route resources on an XC7Z020 with DSP inference
disabled so that every point is built from the same fabric. The comparison is
validated on hardware rather than in simulation alone.

Our contributions are:

1. **A post-route comparison at an equal budget.** At 64 multipliers the
   tap-banking core uses 29% fewer LUTs and 57% fewer flip-flops than the
   output-channel core. The mechanism is visible in the structure: the
   output-channel axis replicates a 32-bit accumulator per channel, while the
   banking axis sums its products in an adder tree and shares one accumulator.

2. **It is also faster in time, not only smaller.** The banking core issues 5.1%
   more cycles per window, but closes timing with 1.040 ns of slack against
   0.157 ns, so at 111.6 MHz against 101.6 it finishes a window in 8.57 us
   against 8.96 -- 4.4% sooner. The output-channel core at this budget is
   limited by a 64-way output multiplexer and 64 weight-memory ports.

3. **The cost per multiplier is not a constant, and diverges with scale.**
   Flip-flops scale linearly, at 111 per multiplier against 45. LUTs do not:
   at a small budget the two axes cost about the same per multiplier (98
   against 99), and by the largest budget measured the output-channel axis has
   risen to 134 while banking stays near 93. The gap is a property of scale, not
   a fixed rate.

4. **A measurement of what static assignment costs.** Assigning tap *t* to bank
   *t* mod *T* performs no load balancing. On this layer the penalty is 1.16x at
   *T*=4 and 1.35x at *T*=8, and it is already contained in the cycle counts
   reported above rather than being an unmodelled overhead.

5. **Hardware validation of the cycle model.** On an XC7Z020 at 100 MHz the
   measured cycle count equals the simulated one exactly, with the design's own
   stall counters reading zero, so the figure describes the core and not the
   memory path feeding it. All 1,605,632 outputs of a complete feature map match
   an integer reference.

We do not claim the equal-multiplier comparison itself as a contribution; as
noted above, working at a fixed multiplier count is the premise of [1] and [2].
What is new here is that the axis those works reject, for reasons that do not
hold under sparsity, is cheaper per multiplier than the axis they adopt -- and
by how much.

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

- Where to Spend the Multipliers in a Sparse CNN Accelerator
- Tap Banking versus Output-Channel Parallelism at an Equal Multiplier Budget
- The Cheaper Axis: Sparse Tap Banking on a Small FPGA
- Revisiting the Rejected Axis in Sparse CNN Acceleration
