## II. Architecture

### A. The unit of work

All four cores compute the same thing: given a window of *K* activations and the
weights of *COUT* output channels, they produce

    y[c] = max(0, bias[c] + sum over t of x[t] * w[c][t])

with activations in 0..127, weights signed INT8 and the accumulation in INT32.
The host is required to prove that `|bias[c]| + 127 * sum |w[c][t]|` stays inside
INT32, so no saturation logic is needed in the datapath. For the layer studied
here, `features.3` of a quantized VGG11, *K* = 576 and *COUT* = 128.

Only *P* output channels are computed at once. A window is therefore issued
`GROUPS = ceil(COUT/P)` times, once per group of *P* channels, and *P* sets the
width of the output datapath.

### B. Skipping zeros

Zero activations are removed as the window is loaded, not as it is computed. A
tap is written into a tuple memory only when it is nonzero, together with its
original tap index:

```verilog
if (s_valid && s_ready && (!mode || s_data != 0))
    tuple_mem[count] <= {input_tap, s_data};
```

Storing the index is what makes the compression usable: once zeros are dropped,
position in the tuple memory no longer says which weight a value belongs to.

The consequence is that the input stream is unchanged -- *K* beats arrive per
window whether or not they are mostly zero -- while the number of issue cycles
falls to the number of stored tuples. The saving is in multiplications, not in
bandwidth.

Fig. 1 shows the three structures side by side.

### C. Channel: spending multipliers on output channels

The **Channel** core (`overlapped_window_mac`) issues one tuple per cycle and computes *P* channels
from it, so it holds *P* multipliers. Its tuple memory is double buffered, so
the host can stream window *w*+1 while window *w* is still issuing; the issue
engine moves from the last group of one window to the first group of the next
without a gap. An all-zero window is handled by issuing a single pseudo tap per
group with its product forced to zero, which keeps the bias and ReLU path
identical rather than adding a state.

Each of the *P* lanes owns a weight memory and, importantly, a 32-bit
accumulator. Widening this axis replicates both.

Issue cycles per window: `GROUPS * nnz`, where *nnz* is the number of nonzero
taps.

### D. Bank: spending multipliers on tap banks

The **Bank** core (`banked_window_mac`) keeps that structure and adds a second axis. Tap *t* is
assigned to bank *t* mod *T* at row *t*/*T*. Each bank has its own tuple memory,
and each lane has *T* weight memories indexed by (group, row). Every issue cycle
reads one tuple from every bank, so *P* x *T* products are formed per cycle.

The products of one lane are summed in an adder tree before they reach the
accumulator:

```verilog
tree = 0;
for (b = 0; b < T; b = b + 1)
    tree = tree + product[l][b];
psum[l] <= tree;
```

This is the structural difference the paper measures. Adding a multiplier on the
*P* axis adds an accumulator -- a 32-bit register with its adder, live across the
whole window. Adding one on the *T* axis adds a branch of the adder tree, and the
accumulator stays shared. The cost of the two is not the same.

Three things are deliberately *not* duplicated. The weight memory is split
across banks rather than replicated, so its total size is unchanged: lane
weights for taps with `t mod T == b` are indexed by (group, `t/T`), giving
`GROUPS * ceil(K/T)` entries per bank and `GROUPS * K` in total, exactly as in
Channel. The tuple memory is likewise partitioned. The pipeline gains one stage, the
tree sum, for four in total.

Issue cycles per window: `GROUPS * max over banks of nnz_b`. The banks run in
lockstep, so a window costs as long as its fullest bank, not the sum. Banks that
run out issue nothing and their product is forced to zero.

### E. The comparison

The two axes therefore reach the same multiplier count by different routes:
Channel holds *P* multipliers, Bank holds *P* x *T*. A budget of 64 multipliers
is Channel with *P* = 64, or Bank with *P* = 16 and *T* = 4, or several points
between. Cycles per
window differ only through the divisor -- *nnz* against max_b *nnz_b* -- while
the logic that surrounds those multipliers differs in kind.

### F. Integration

The cores are wrapped by `window_mac_axis`, which presents AXI4-Stream in and
out and an AXI4-Lite register file. The wrapper packs four activations per
stream beat, walks the weight and bias stream in configuration mode, and counts
cycles, completed windows and input and output stall cycles in hardware. The
stall counters are what make a measured cycle count meaningful: a run in which
they are nonzero measured the memory path, not the core. `K` and `COUT` are the
memories' built-in maxima, with the size actually used set at run time, so one
bitstream covers any layer whose weights fit.
