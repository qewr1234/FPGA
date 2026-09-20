# Window MAC cores for a quantized CNN layer (v1–v4)

Four SystemVerilog cores that compute one convolution window — `MAC + bias + ReLU` over `K` taps
and `COUT` output channels — with progressively more overlap and parallelism, plus the test bench,
integer oracle and cycle model used to check them.

Korean documentation is the primary reference: **[README_KO.md](README_KO.md)** (design)
and **[RESULTS_KO.md](RESULTS_KO.md)** (measurements). This page is a summary.

| Core | File | Idea |
|---|---|---|
| v1 | `rtl/sparse_window_mac.sv` | Per group: compute → output → next group |
| v2 | `rtl/continuous_window_mac.sv` | Continuous group issue **within** a window (result-slot reservation) |
| v3 | `rtl/overlapped_window_mac.sv` | Overlap **across** windows: receive window `w+1` while computing window `w` |
| v4 | `rtl/banked_window_mac.sv` | v3 + `T` tap banks issuing `T` tuples per cycle (`P×T` multipliers) |

`P` is the number of output-channel lanes, `T` the number of tap banks, `DEPTH` the result-slot depth.
Activations are 7-bit unsigned (0..127), weights signed INT8, sums INT32.

## What was measured

Icarus Verilog 12.0 behavioral simulation. **No synthesis, place-and-route, Fmax, resource, power
or board data** — see "Not established" below.

- 167 RTL test configurations (141 synthetic + 26 on real VGG11 `features.3` windows), one test bench for all four cores.
- 3,447,344 outputs checked against a Python integer oracle — 0 mismatches.
- 30,992 per-window `(start, end)` cycle rows checked against an independent per-edge protocol
  model (`scripts/stream_model.py`) — 0 mismatches.
- Real data: 512 windows per split × alternating dense/sparse = 1,024 windows streamed back to back.

Throughput on the same stream (evaluation split, cycles per window, lower is better):

| Multipliers | v3 (`P` lanes, `T=1`) | v4 (`P`, `T`) |
|--:|--:|--:|
| 8 | `P=8` → **7,230.6** | `P=2, T=4` → 7,641.0 |
| 16 | `P=16` → **3,615.6** | `P=8, T=2` → 3,697.2 |
| 32 | `P=32` → **1,808.1** | `P=8, T=4` → 1,910.7 |
| 64 | `P=64` → **910.7** | `P=16, T=4` → 956.8 · `P=8, T=8` → 1,019.6 |
| 128 | `P=128` → **577.3** (input wall) | — |

v3 removes ~582 cycles per window versus v2 — the `K=576` input load plus handshake — by hiding the
load of window `w+1` under the compute of window `w`. That is a real, reproducible win.

**A v4 core at `(P, T)` costs `P×T` multipliers, so its baseline is v3 with `P×T` lanes, not v3 with
`P` lanes.** At equal multiplier count, adding lanes beats adding banks at every budget on this layer,
and the gap depends only on `T` (+2.3% at `T=2`, +5.1‥5.7% at `T=4`, +12.0% at `T=8`) — the cost of a
static tap interleave, whose bank imbalance is 6.2 / 15.7 / 35.1% on real sparse windows.
At `P=128` v3 alone reaches the `K`-beat input wall at 577.3 cycles per window, which is the ceiling
for both cores here.

So **no measurement in this repository currently supports the v4 banking direction on cycle count.**

Out-of-context synthesis (Vivado 2026.1, xc7z020clg484-1, 100 MHz) does not rescue it either. At 32
multipliers, v3 `P=32` closes at 107.40 MHz and v4 `P=8, T=4` at 107.99 MHz — a 0.5% difference, far
short of the 5.7% Fmax advantage v4 would need to overturn its cycle deficit. Per window that is
**16.84 µs for v3 against 17.69 µs for v4**. The T-sum adder tree, which this repository previously
expected to cost v4 its clock, is not on the critical path at T=4: all four cores are limited by the
same 7x8 multiply carry chain.

Two things keep the question open. Those runs left the port paths unconstrained, which hides the
`DEPTH*P : 1` output multiplexer — the path that grows with `P`, measured at 12.7 ns for v3 `P=32`
while WNS still read 0.689 ns. And a layer whose `COUT` caps `P` before the input wall has not been
measured at all. See `RESULTS_KO.md` for the full tables.

## Running the checks

Python 3.9+ and Icarus Verilog (`iverilog`, `vvp`).

```sh
python scripts/run_stream_checks.py --suite smoke --jobs 4   # 141 synthetic configurations
python scripts/run_stream_checks.py --suite full  --jobs 4   # + 26 real-data configurations (167 total)
python scripts/make_results.py build/stream_<stamp>          # comparison table
```

The run is deterministic: a fresh run reproduces the committed numbers exactly. Evidence from the
included run — source snapshot, per-case cycle CSVs, simulation logs, aggregate summary — is in
`verification/included_run/`.

Out-of-context Vivado synthesis is scripted in `scripts/synth_vivado.tcl` (or `RUN_SYNTH.cmd` on
Windows) but was **not run** — no Vivado in the development environment.

## Layout

```
rtl/            four window MAC cores
sim/            tb_stream_compare.sv — one bench, all four cores, same stream
scripts/        check runner, integer oracle, independent cycle model, bank projection, Vivado TCL
data/           quantized VGG11 features.3 windows + provenance metadata
verification/   committed evidence from the included run
```

## Not established

Synthesis, place-and-route, Fmax, resources, power, DSP/BRAM usage, AXI/DMA integration, whole-network
timing, classification accuracy and board behaviour are all outside this package. Cycle counts are not
time: `latency = cycles / Fmax`, and Fmax has not been measured for any core.

## License

See [LICENSE](LICENSE).
