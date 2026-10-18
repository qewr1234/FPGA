# Related work: offline channel-to-bank permutation for a lockstep-bank zero-skipping core

Draft section for the English journal brief. Each [n] is the entry with
`"n": n` in `bankperm/references.json`. Every entry there was checked on
2026-10-18 against Crossref, the arXiv API, NeurIPS proceedings metadata or the
patent record; the `verified` field of each entry says how much of the paper
was read.

## II. Related Work

**Zero skipping and lane synchronization.** Cnvlutin [1] skips zero
activations by splitting each window's input channels into 16 slices, one per
lane, and rearranging the weights statically to match. All lanes then advance
one window at a time, so lanes with fewer nonzeros idle until the slowest lane
finishes. SCNN [2] exploits sparsity in both operands and reports cycles lost
to load imbalance at inter-PE barriers; SparTen [3] traces such imbalance to
broadcast reuse of input maps across filters of different density. Cambricon-X [4] exploits weight sparsity, and
NullHop [5] exploits activation sparsity on a Zynq FPGA. The
core studied here has the same structure: its four banks run in lockstep, so
each window costs as much as its fullest bank.

**Balancing by changing the network.** ESE [6] and bank-balanced sparsity [7]
prune weights so that each PE or bank holds a balanced number of nonzeros. S2TA
[8] caps the nonzeros in each activation block by run-time top-NNZ pruning,
which is lossy and needs fine-tuning. A Moffett patent [9] keeps the top-k
activations in each bank. BRIM [10] reshapes weights offline (Cyclic-Balanced
Pruning) from profiled activation statistics and adds hardware for the
remaining imbalance. All of
these change the function the network computes.

**Balancing at run time.** Sense [11] ranks input channels by nonzero count in
hardware, with a ranking unit, a crossbar and FIFOs, and states that, since
input maps are generated dynamically, "they cannot be trained offline to
balance IFM workload". Crane [12] moves work between PEs at run time. SpALEn [13] and Guo et al. [14] also
rely on run-time logic or scheduling.

**Offline, function-preserving permutations.** SparTen's software greedy
balancing [3] sorts filters by density offline and reorders the next layer's
weights to match. Pool and Yu [15] permute channels so that N:M pruning keeps
more weight magnitude, and fold the permutation into the preceding layer.
TETRIS [16] reorders input and output dimensions so that small weights form
prunable blocks, and keeps one reordering per layer at run time. On FPGAs, Xu
et al. [17] sort channels by weight workload, and SparHiXcel-v2 [18] searches
channel and filter orders for weight sparsity. All of these optimize a
property of the weights. Activation statistics drive offline reordering in
VARA [19], which profiles co-zero affinity over sliding windows and permutes
input dimensions to cluster zeros, applying the order at run time through an
index unit. Neuralink [20] and PowerInfer [21] use them to place neurons in
storage or on a device, not to balance parallel units.

**Problem class and cost model.** For one layer, assigning C channels to T
equal-size banks so as to minimize the sum over windows of the fullest bank's
nonzero count is a cardinality-constrained, sum-of-maxima variant of
multi-constraint partitioning [22] and vector scheduling [23]. SELL-C-σ [24]
sorts sparse-matrix rows for a similar reason: to reduce padding in lockstep
SIMD lanes. Skewed storage [30] places a matrix in parallel memories so that
its rows and columns can be accessed without bank conflicts, the classic
form of spreading correlated items over banks by a fixed index rule. The cycle model refines roofline-style analysis [25], [26] to
individual windows. The networks are DnCNN-style denoisers [27], tested on
Set12 [27] and BSD68 [28], [29].

## Novelty position

We do not claim that channel permutation, folding it into adjacent layers [3],
[15], offline profiling of activations [10], [19]–[21] or greedy local search
is new, and lane-synchronization stalls are known [1]. The claim is narrower.
In a zero-skipping integer core whose banks run in lockstep and receive taps by
a fixed index rule (tap t goes to bank t mod 4), the assignment of channels to
banks is a free variable once the (ky, kx, channel) window order is fixed. (On
this platform the host builds the windows, so the order of the taps inside a
window is free as well; that larger space, which includes skewed layouts in
the sense of [30], is not evaluated here.) We fix it once, from calibration activations, to
minimize the expected per-window bank maximum. The permutation is folded into
the producer's filters, bias and requantization and into the consumer's
weights, so the RTL, the bitstream and the integer output are unchanged for
every input. The objective differs from the weight-driven permutations [3],
[15]–[18]. Unlike Sense and Crane [11], [12], the method needs no run-time
hardware. Unlike VARA [19], it spreads co-active channels across parallel banks
instead of clustering zeros, and it leaves no run-time index. Unlike skewed
storage [30], the assignment is fitted to activation statistics. Because
activations change with the input, the balance holds only in expectation, not
for every image. The contribution is therefore empirical: how much of the
bank-imbalance cost a fixed relabelling removes on held-out images, how much of
it a density-only heuristic reaches (about half; this compares procedures and
does not isolate co-activation), and agreement between predicted and
board-measured cycles. Our search
(Crossref, arXiv and the web, October 2026) found each element separately but
no work that combines them.

## Notes for the authors (not for the manuscript)

- Sense's wording is quoted from its arXiv v2 (Sec. III-B). Crane's full text
  is closed access, and its wording on offline balancing could not be
  re-checked, so the draft no longer attributes that point to Crane.
- SparTen GB-S sorts whole filters by density and unshuffles the next layer's
  weights statically; pairing dense and sparse filters on one compute unit is
  GB-H (Gondimalla's dissertation, Sec. 3.3.3), not GB-S.
- Do not call Xu et al. [17] the closest prior work: it balances weight
  workload and leaves activation sparsity to future work. Sense [11] is the
  closest work on activation balancing, and SparTen GB-S [3] is the closest on
  the folding mechanism.
- `paper/RELATED_WORK_KO.md` §3–4 attributes the crossbar overhead to Xu et
  al.; Xu et al. say it of Xie et al., IEEE TCAS-I 68(7):2936–2949, 2021. The
  Xu et al. paper is Micromachines 16(1):22, 2025 (online 27 Dec 2024). See
  `related_work_ko_audit` in `references.json`.
- Zhu et al. (Microelectronics J. 2026) and Wang et al. (J. Syst. Archit. 2026)
  are left out: only their metadata could be verified. "SparDR" was not found.
- Do not write that bank balancing "is not available for activation sparsity":
  [8] and [9] do it by discarding activations. The defensible contrast is
  function preservation.
