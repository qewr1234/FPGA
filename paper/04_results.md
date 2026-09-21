## IV. Results

### A. Reading the comparison correctly

It is worth stating first what this work does *not* report. Measured on its own,
v4 at *P* = 8, *T* = 8 processes a window in 1,019.6 cycles against 7,230.6 for
v3 at *P* = 8 -- a reduction of 85.9%. That number is meaningless: the first
core holds 64 multipliers and the second holds 8. Read across an axis of
differing resources, almost any architecture can be made to look good.

Read at a fixed budget instead. At 64 multipliers, v3 with *P* = 64 takes 910.7
cycles per window and v4 with *P* = 16, *T* = 4 takes 956.8, a difference of
5.1% (Fig. 2). Spending the same multipliers on tap banks rather than on output
channels costs essentially nothing in throughput.

### B. Cost per multiplier

The resource figures are the point of the paper. Table I gives every
configuration that Vivado built without inferring DSP blocks, which is the set
that can be compared.

**TABLE I. Post-route utilisation, xc7z020clg484-1, 10 ns, DSP inference off.**

| Core | *P* | *T* | Multipliers | Total LUTs | Logic LUTs | LUTRAM | FFs |
|---|---|---|---|---|---|---|---|
| v3 | 8 | 1 | 8 | 1,209 | 1,033 | 176 | 995 |
| v3 | 32 | 1 | 32 | 4,534 | 3,830 | 704 | 3,674 |
| v4 | 2 | 4 | 8 | 1,004 | 916 | 88 | 605 |
| v4 | 4 | 4 | 16 | 1,795 | 1,707 | 88 | 953 |
| v4 | 8 | 4 | 32 | 3,159 | 2,983 | 176 | 1,656 |

Taking the slope between the smallest and largest configuration of each core
gives the cost of widening by one multiplier:

|  | LUTs per multiplier | FFs per multiplier |
|---|---|---|
| Output-channel axis (v3) | 138.5 | 111.6 |
| Tap-banking axis (v4) | **89.8** | **43.8** |
| Difference | **-35%** | **-61%** |

The flip-flop gap is the larger of the two and is the one the architecture
predicts. Every multiplier added on the *P* axis brings a 32-bit accumulator
that must hold its value for the whole window; every multiplier added on the *T*
axis brings a branch of an adder tree, and the accumulator behind it is shared.
Ma et al. observe of their own design that logic is used mainly for the
accumulators in the MAC units [2]; the measurement here is what that observation
costs when the two axes are priced against each other.

v4 linearity supports reading the slope as a rate rather than as two endpoints:
fitted through the outer two points, the middle point is predicted to within
0.2% on flip-flops and 4.0% on LUTs. v3 has only two DSP-free points, so its
figure is a line through two measurements rather than a fit -- a limitation
noted in Section V.

### C. Where the output datapath cost sits

Distributed RAM comes to 22 LUTRAM per output lane at every DSP-free point with
*P* >= 4, in both architectures: v3 at *P* = 8 and *P* = 32, v4 at *P* = 4 and
*P* = 8. It tracks *P* and not *P* x *T*. This is direct evidence for the
mechanism above -- the output datapath is sized by the number of output channels
in flight, not by the number of multipliers -- and it is why the banking axis can
add multipliers without paying for them twice. (v4 at *P* = 2 floors at 88
rather than following the relation, the only DSP-free point that does not.)

Block RAM is effectively unchanged: 33 RAMB36 for v3 against 32 RAMB36 plus 4
RAMB18 for v4. Splitting the weight memory across banks, rather than replicating
it, keeps the stored bits the same, as Section II-D describes.

### D. Repeatability

Repeating a configuration moves the LUT count by at most 2, and three separate
runs of v3 at *P* = 32 span 3 LUTs (4,535 / 4,535 / 4,532). Flip-flop counts
repeat exactly. The differences reported above are between one and two orders of
magnitude larger than this.

### E. What the static assignment costs

Assigning tap *t* to bank *t* mod *T* does no load balancing, and the banks run
in lockstep, so a window costs as long as its fullest bank. On the evaluation
data this is measurable:

| *T* | Mean imbalance | Worst window |
|---|---|---|
| 2 | 1.062x | 1.188x |
| 4 | 1.157x | 1.469x |
| 8 | 1.351x | 2.059x |
| 16 | 1.639x | 2.557x |

This is not an unmodelled overhead. The cycle counts in Section IV-A were
measured on this same data and already contain it; the 5.1% figure is what
remains after the imbalance has been paid. The table also explains why *T* is
not pushed further: the penalty grows faster than the parallelism beyond *T* = 8.

### F. Hardware

The v3 core at *P* = 8 was placed on an XC7Z020-CLG484 at 100 MHz, closing
timing with 0.919 ns of slack, and run over 1,024 windows of real data.

| | |
|---|---|
| Outputs checked | 131,072 |
| Mismatches | **0** |
| Cycles | **7,404,123** |
| Cycles per window | 7,230.59 |
| Input stall cycles | 0 |
| Output stall cycles | 0 |

The measured cycle count equals the simulated one exactly. Both stall counters
read zero, so the DMA never starved the core and never blocked its output: the
figure describes the accelerator, not the memory path feeding it. This is the
condition under which a hardware number is comparable with a simulated one, and
it is reported rather than assumed.

A second run streamed a complete 112 x 112 feature map from one image -- 12,544
contiguous windows, 1,605,632 outputs -- all of which matched the reference
(Fig. 8). The software and hardware feature maps are indistinguishable and their
difference is uniformly zero.
