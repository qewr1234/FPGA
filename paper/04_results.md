## IV. Results

### A. Reading the comparison correctly

It is worth stating first what this work does *not* report. Measured on its own,
Bank at *P* = 8, *T* = 8 processes a window in 1,019.6 cycles against 7,230.6 for
Channel at *P* = 8 -- a reduction of 85.9%. That number is meaningless: the first
core holds 64 multipliers and the second holds 8. Read across an axis of
differing resources, almost any architecture can be made to look good.

Read at a fixed budget instead. At 64 multipliers, Channel with *P* = 64 takes
910.7 cycles per window and Bank with *P* = 16, *T* = 4 takes 956.8, a difference of
5.1% (Fig. 2). Spending the same multipliers on tap banks rather than on output
channels costs essentially nothing in throughput.

### B. Cost at an equal budget

Table I gives every configuration Vivado built without inferring DSP blocks,
which is the set that can be compared.

**TABLE I. Post-route utilisation, xc7z020clg484-1, 10 ns, DSP inference off.**

| Core | *P* | *T* | Multipliers | Total LUTs | LUTRAM | FFs | WNS (ns) |
|---|---|---|---|---|---|---|---|
| Channel | 2 | 1 | 2 | 992 | 520 | 363 | +0.888 |
| Channel | 16 | 1 | 16 | 2,360 | 352 | 1,895 | +0.942 |
| Channel | 64 | 1 | 64 | 8,812 | 1,408 | 7,248 | +0.157 |
| Bank | 2 | 4 | 8 | 1,004 | 88 | 605 | +0.892 |
| Bank | 4 | 4 | 16 | 1,795 | 88 | 953 | +0.862 |
| Bank | 8 | 4 | 32 | 3,159 | 176 | 1,656 | +0.961 |
| Bank | 16 | 4 | 64 | 6,218 | 352 | 3,107 | +1.040 |

At the 64-multiplier budget both bitstreams were built for:

|  | Channel, *P* = 64 | Bank, *P* = 16, *T* = 4 |  |
|---|---|---|---|
| Total LUTs | 8,812 | **6,218** | **-29%** |
| Flip-flops | 7,248 | **3,107** | **-57%** |
| Cycles per window | **910.7** | 956.8 | +5.1% |
| WNS | +0.157 ns | **+1.040 ns** |  |
| Fmax | 101.6 MHz | **111.6 MHz** |  |
| Time per window | 8.96 us | **8.57 us** | **-4.4%** |

The last two rows are what makes the comparison decide rather than trade. Bank
issues more cycles, but Channel at *P* = 64 barely closes: a 64-way output
multiplexer and 64 weight-memory ports leave 0.157 ns of slack against Bank's
1.040 ns. Converted to time, the core that costs 29% fewer LUTs and 57% fewer
flip-flops also finishes the window 4.4% sooner.

### C. Cost per multiplier, and why it is not one number

Flip-flops scale linearly in both cores. Channel costs 109.4 per multiplier from
2 to 16 and 111.5 from 16 to 64; Bank costs 43.5, 43.9 and 45.3 across its three
segments. Reporting 111 against 45, a 60% difference, is sound.

LUTs are not linear for Channel:

| Segment | Channel | Bank |
|---|---|---|
| small budget | 97.7 / mult (2 to 16) | 98.9 / mult (8 to 16) |
| mid | -- | 85.2 / mult (16 to 32) |
| large budget | **134.4 / mult** (16 to 64) | 95.6 / mult (32 to 64) |

At a small budget the two axes cost about the same per multiplier. Bank stays
near 93 throughout, while Channel rises by more than a third as the budget
grows. The gap this paper reports is therefore not a fixed rate but something
that opens with scale -- which is the regime a fixed multiplier budget puts a
designer in. A single slope for Channel would misstate it in both directions,
so none is quoted.

Channel is measured at three points and Bank at four; the segment figures above
are what those support.

### C. Where the output datapath cost sits

Distributed RAM comes to 22 LUTRAM per output lane at every DSP-free point with
*P* >= 4, in both architectures: Channel at *P* = 8 and *P* = 32, Bank at
*P* = 4 and *P* = 8. It tracks *P* and not *P* x *T*. This is direct evidence for the
mechanism above -- the output datapath is sized by the number of output channels
in flight, not by the number of multipliers -- and it is why the banking axis can
add multipliers without paying for them twice. (Bank at *P* = 2 floors at 88
rather than following the relation, the only DSP-free point that does not.)

Block RAM is effectively unchanged: 33 RAMB36 for Channel against 32 RAMB36 plus
4 RAMB18 for Bank. Splitting the weight memory across banks, rather than replicating
it, keeps the stored bits the same, as Section II-D describes.

### D. Repeatability

Repeating a configuration moves the LUT count by at most 2, and three separate
runs of Channel at *P* = 32 span 3 LUTs (4,535 / 4,535 / 4,532). Flip-flop counts
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

The Channel core at *P* = 8 was placed on an XC7Z020-CLG484 at 100 MHz, closing
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
(Fig. 4). The software and hardware feature maps are indistinguishable and their
difference is uniformly zero.
