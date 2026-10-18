# Q1 FPGA Denoising Co-Design — Stage 1: Safe preflight

**Research goal:** Quality-constrained memory–compute co-design, XC7Z020 / Smart ZYNQ SL, Vivado 2026.1, RTX 4060 Ti.

## Windows CMD: run now

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_Q1_PREFLIGHT.cmd
```

Preserve local changes before git pull if git status shows changes. Share the generated file `build/q1_preflight/report.json` and any errors.

The preflight checks the Vivado version, XSDB path, pretrained model, Set12 dataset, integer exports, and any existing local W=4 bitstream. It **does not** rebuild or program the FPGA and needs only standard-library Python.

## Board safety gate

`scripts/build_zedboard.tcl` defaults to a **ZedBoard PS7 preset**. Even though the FPGA device is XC7Z020, this does not prove that Smart ZYNQ SL uses the same DDR device/settings, PS clock, MIO map or reset wiring. **Do not run the existing bitstream on Smart ZYNQ SL until these have been checked.** Existing W=4 timing/utilization reports in GitHub are historical and do not establish compatibility with this physical board.

## Research execution gates

1. **Gate 0 — reproducibility and safety:** Vivado 2026.1, Smart ZYNQ SL PS7/DDR/MIO verified, W=4 timing closure, 0 mismatches against integer reference.
2. **Gate 1 — bottleneck profile:** independently measure host im2col, data transfer, AXI DMA/PL cycles, intermediate requantization, and complete measured host pipeline, excluding JTAG launch overhead from the computational latency claim.
3. **Gate 2 — prototype:** only after Gate 1, prototype 2-layer local buffering/fusion; compare unchanged INT8 outputs, BRAM/LUT/WNS and actual DDR traffic against the same-W=4 baseline.
4. **Gate 3 — joint optimization:** train/evaluate controlled CNN choices with RTX 4060 Ti, compare PSNR/SSIM versus true FPGA latency and resources at matched quality.

The initial Go/No-Go is a measured DDR-traffic or host preprocessing bottleneck. If computation is already the bottleneck, fusion may not help and the architecture should be changed instead.

All generated outputs are under gitignored `build/`. Nothing in the previous RTL, exported models, or board reports is overwritten.
