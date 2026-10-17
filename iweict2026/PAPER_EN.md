# Designing to the Bottleneck, Not the FLOPs: CNN Image Denoising on an Input-Bandwidth-Bound Small-FPGA Integer Accelerator

(Author), (Department, University), (e-mail)

> **Draft notes (remove before submission)**
>
> - 2026-10-15. Condensed from `PAPER_KO.md`; every number is from the committed files listed there. [MAXOUT] marks the sentences and table rows that the fixed-budget re-run (ReLU, averaging control, maxout; 120 epochs + 15 QAT epochs each) will fill.
> - 2026-10-16. Seed-1 fixed-budget result (integer, after QAT): ReLU 29.62 / 28.68, maxout 30.00 / 28.94 (logs, 2 decimals). Not filled in yet: the seed-1 ReLU run collapsed at epoch 26 and the plateau rule halved its rate four times during the recovery, so seeds 2 and 3 decide (rule in `ABSTRACT.md`). The line-buffer sentences now say what the model predicts (maxout stops being free; B becomes slower than A).
> - 2026-10-16, later. The speed model is now the fixed-budget `dn_d10_c32_us_mo_fx_qat` (board run 0 mismatches, 44,254,293 cycles), the arm of the controlled comparison; the B-32 ReLU + QAT network was also run on the board (43,811,412 cycles, 668.5 per pixel against 668.5 modelled). Seven models are now verified on the board. The ReLU row shows seed 1 (as Fig. 2 does); the averaging row waits for its QAT; seeds 2 and 3 will turn the B-32 rows into means.
> - Build into the workshop template: `python iweict2026/build_docx.py --tpl iweict2026/template_word.docx --src iweict2026/PAPER_EN.md --out iweict2026/PAPER_EN.docx --lang en --col-fig-cm 7.6 --ack "<English acknowledgment>"` (Fig. 1 at 7.6 cm keeps four pages).
> - 2026-10-16, reframing. The averaging control matched maxout (seed 1, float), so the second contribution is now the free capacity of pooled extra outputs, not the max; a parameter-matched ReLU network (45 channels) is given by the cycle model only; the conclusion says what carries over beyond this core. [SEEDS] marks the claims seeds 2 and 3 confirm or remove (rule in `ABSTRACT.md`); [AVG] the averaging control's QAT values.
> - The board-output figure (Korean draft, Fig. 3) is left out for space.
> - 2026-10-17. Seeds 2 and 3 (GPU PC) are in. Integer, after QAT, Set12 / BSD68: ReLU 29.62 / 28.68, 29.94 / 28.91, 29.89 / 28.88; maxout 30.00 / 28.94, 29.91 / 28.89, 29.99 / 28.95. Seed 2 reverses (−0.03 / −0.02 dB), so the rule in `ABSTRACT.md` gives (c): the abstract ends the maxout sentence at "1% more cycles" and the paper no longer claims that pooling denoises better. The 45-channel ReLU network (30.05 / 28.97) and the averaging control's seed 2 (29.82 / 28.82) are reported; the averaging control's seed-1 QAT and files are still on the first PC and must be pushed before "Code, models and board logs are in the repository" holds. Seeds 2–3 ran the training code from before commit 261952a, i.e. PyTorch's GPU defaults (TF32 convolutions where the GPU has them), not the fp32 setting that commit added.
> - 2026-10-17, night. A four-value-per-cycle variant of the core (W=4) was built and RTL-simulated on 512 real windows of every layer of the four networks (`denoise/sim_w4_layers.py`): outputs exact, cycles within each layer's fill and drain of the per-window count (`denoise/wider_ports.py`), which replaces the Korean Table III's density-based estimate (that estimate assumed one bank imbalance for both networks and overstated maxout/ReLU at w = 4: 2.59–2.79 against 2.48 counted). Not yet run on the board; when it is, the Section II sentence and the abstract's parenthesis become the measurement. Section IV counts include the W=4 builds.
> - 2026-10-17, later. The W=4 bitstream (WNS +0.130 ns at 100 MHz; 21% LUTs, 51% BRAM) ran the four networks on the board (`denoise/board_runs/*_05_w4.json`; `denoise/compare_w4.py` → `w4_measured.json`): 0 mismatches, PSNR as at W=1, totals 0.0009–0.0044% above `w4_prediction.json` (committed in 7e81f6b before the bitstream existed), per layer 9–164 cycles (fill and drain), IN_STALL 12 cycles in all (ReLU conv5), OUT_STALL 0. B/A 1.194 (W=1 0.746), maxout/ReLU 2.482 (W=1 1.010). The abstract, introduction, Section II, IV and the conclusion now say board; w = 2 and line buffers stay predictions. In all 29 hidden layers, at W=1 and W=4, on the board and in the RTL sample, the gap minus IN_STALL is min(window load, last window's compute) + 19 cycles, and on the last layers + COUT + 3 (`denoise/w4_gaps.py` → `w4_gaps.json`; read off after the run), which is what "fill and drain" in Section II refers to. Table II's PSNR column (05.png, the same at W=1 and W=4) gave way to the w = 4 column.

## Abstract

Efficient neural networks are usually designed to minimize multiplications, but on a small accelerator the run time may be set by something else. On our integer CNN core for a Zynq XC7Z020 FPGA (64 multipliers, 7-bit inputs), we show how the measured bottleneck changes the design of a Gaussian denoiser. A cycle model, corrected on earlier board runs and within 0.003% of the board on four networks, shows that this build, fed host-built windows one value per cycle, is bound by its input port: a window of K values costs K cycles for up to 64 output channels, so a DnCNN-style baseline leaves most multipliers idle. Two choices that look wasteful by FLOP count are therefore cheap. A 2×2 space-to-depth input fits a 6.4× larger network in 25% fewer cycles. Doubling the hidden outputs and pooling them in pairs (maxout) doubles the parameters for 1% more cycles. With quantization-aware training that reproduces the board's arithmetic, the quality model reaches 30.12 dB on Set12 (σ = 25), above BM3D on the same input, and the speed model matches BM3D in 2.63× fewer cycles than the baseline; four networks were verified bit for bit on the board, a full image each. The cycle model predicts that with two input values per cycle pooling stops being free, and with four (on a four-value variant the board matched it within 0.005%) or with line buffers the 6.4× larger network becomes slower than the baseline: the network to choose follows the measured bottleneck.

**Keywords** — image denoising, CNN accelerator, FPGA, hardware-aware network design, maxout, quantization-aware training

## I. Introduction

CNN denoisers such as DnCNN [1] outperform the classical BM3D [2] but need tens of thousands of multiplications per pixel, and networks for an accelerator are usually chosen by their multiplication or parameter count. That count is known not to set the run time. The roofline model [3] explains why kernels of low arithmetic intensity are bound by bandwidth rather than compute; ShuffleNet V2 [4] derived design rules from measured GPU speed; EfficientNet-X [5] analysed the gap between FLOPs and latency on TPUs and GPUs and used space-to-depth to raise accelerator utilization; and ABPN [6] built an INT8 super-resolution network from operator latencies measured on a mobile NPU. FPGA CNN accelerators remove memory-bandwidth bottlenecks with on-chip pipelines and line buffers [7]; eCNN [8] co-designed restoration networks with a DRAM-bandwidth-limited accelerator; and light CNN denoisers have been put on Zynq-class FPGAs [9], [10] and on a vendor DPU with INT8 quantization-aware training [11]. These works measure GPU, TPU, NPU or DPU latency or model DRAM traffic. Closest to ours, HALP [12] prunes channels to a GPU's measured latency steps, and DRACO [13] reshapes memory-bound networks to fill a fixed systolic array.

We study the same principle at a smaller scale and at cycle level, measured on the board rather than simulated, on an integer CNN core of our own design for a Zynq XC7Z020, a test vehicle, slower than a PC CPU (Section V): 64 multipliers, one bitstream that runs every layer with only its shape changed, 7-bit unsigned inputs and a ReLU on every output. Because its input port takes one value per cycle, a window costs the number of values streamed, K, and output channels up to the multiplier count cost nothing. Our contributions are:

1. a cycle model, validated on the board, that separates what is free on this core (output channels up to 64, kernel shape, resampling, host-side operations) from what costs (K);
2. an iso-cycle comparison of two choices that this model favours although they look wasteful by FLOP count: space-to-depth, which fits a 6.4× larger network in 25% fewer cycles, and doubled hidden outputs pooled in pairs (maxout), whose hidden layers keep their cycle count on the board, compared with a same-width ReLU network over three seeds and a mean-pooling control over two;
3. integer models, trained with quantization-aware training that reproduces the board's arithmetic, that beat BM3D on the same input, verified bit for bit on the board.

Space-to-depth [14], [5], maxout [15]–[17] and quantization-aware training [18] are known techniques; our claim concerns the reason for choosing them. It holds for host-built windows fed one value per cycle; with four values per cycle (measured) or on-chip line buffers (predicted) the same model gives different choices (Section II).

## II. Accelerator and Cycle Model

![Fig. 1](../proposal/figures/fig_system_en_col.png)

*Fig. 1. System. The PC builds the windows (im2col) and requantizes between layers; the core in the PL computes every convolution.*

**Core.** The core receives one window of K activations and computes ReLU(b + Σ w·x) for COUT output channels, with INT8 weights, INT32 accumulation and 7-bit activations. Its 64 multipliers are P = 16 output-channel lanes times T = 4 tap banks; K ≤ 1152 and COUT ≤ 128 are set per run, and the same bitstream also runs a CIFAR-10 classifier. The design uses 21% of the LUTs, 51% of the BRAM and, by Vivado's choice in an unrestricted synthesis, no DSP slice. Timing closes at 100 MHz (WNS +0.221 ns); the board runs use the 50 MHz default clock, and a 100 MHz run gave the same cycle count.

**Cycle model.** The input port accepts one value per cycle; output channels are processed P at a time in ⌈K/T⌉ cycles per group while the next window loads. A window therefore costs

  C = max( K, ⌈COUT/P⌉ · ⌈K/T⌉ ).   (1)

When K dominates, the core is input-bound and up to P·T = 64 output channels cost nothing: at K = 288, COUT = 32 and 64 both take 288 cycles. The board showed one cycle more per window (on the CIFAR-10 run and the baseline) and at least COUT cycles per window, as outputs leave one per cycle (settled by B's first layer, K = 36, COUT = 64: 64 cycles). With these two parameter-free corrections, C′ = max(K + 1, ⌈COUT/P⌉·⌈K/T⌉, COUT) matches all four networks within 0.003% (Table II), against 0.4–1.6% without them; the ReLU network, run after they were fixed, was predicted within 0.0014%. All board runs used the sparse mode, which skips zero activations; it shortens only the compute term of (1).

**Where the bottleneck comes from.** One value per cycle is a choice of this design, not a limit of the FPGA: the core's window port takes one value per cycle, and the AXI-Stream wrapper unpacks the four 7-bit values of each 32-bit beat to match it. We treat the core, built for CIFAR-10, as given, as a user of a fixed accelerator would. With w values per cycle, about P·T/w output channels come free. To test this we built a variant that takes a whole beat (w = 4) per cycle, one value per bank. Counting every window of a test image with the feed term ⌈K/w⌉ + 1 (sparse, as on the board), pooling costs 1.55× the ReLU network at w = 2 and 2.48× at w = 4, and B, still 0.82× A at w = 2, costs 1.19× A at w = 4 (by the dense bound, 1.87× and 1.37× already at w = 2). On the board (Table II; WNS +0.130 ns at 100 MHz), the w = 4 variant ran all four networks bit-exactly and within 0.005% of this count, committed before the run; per layer the gap is the pipeline fill and drain (9–164 cycles), plus 12 input stalls in one layer. With on-chip line buffers [7], a window brings one new pixel, C_in values, giving 2.61× and 1.23×. w = 2 and line buffers remain predictions, and the rules below hold for this input structure. Host im2col, requantization and pooling take 0.07–0.13 s per image on a 4-core PC; on hidden layers the last two need fewer operations per window than K and could hide in hardware, while im2col would need line buffers.

## III. Networks Designed to the Bottleneck

**Baseline (A).** A 7-layer, 32-channel 3×3 network derived from DnCNN, with BatchNorm folded. Inputs are clipped to [0, 1] and quantized to 7 bits in training and test. Every output passes a ReLU, so the network cannot predict signed noise as DnCNN does; the last layer outputs the clean image and receives the noisy image as an extra input. A's hidden layers (K = 288, COUT = 32) need 144 cycles of compute but 288 of input, so its multipliers are 41% utilized; more would not make it faster.

**Space-to-depth (B).** As in FFDNet [14], the image is split into its four 2×2 phases and processed at half resolution. With a quarter of the windows, a 10-layer, 64-channel network fits; its hidden layers (K = 576, COUT = 64) balance input and compute exactly, and the network is 88% utilized. It has 6.4× A's parameters and 1.6× its multiplications in 25% fewer cycles, so its gain over A is that of a larger network that space-to-depth makes affordable, not of the resampling alone.

**Free output channels pooled in pairs (B-32 + maxout).** At 32 channels, B's hidden layers return to K = 288 and up to 64 outputs are free again. Each hidden layer computes two candidates per channel, and the host keeps the larger after requantization,

  max(ReLU(a), ReLU(b)) = ReLU(max(a, b)),   (2)

which is maxout [15] in its Max-Feature-Map form [19]. The next layer's K is unchanged, so hidden layers keep their cycle count; only the first layer (K = 36 < 64) grows to 64 cycles per window, 1% per pixel. The pooling makes the free outputs usable: passing all 64 on would double the next layer's K and cycles, and a ReLU network with the same parameters (45 channels, 150k) costs, by the cycle model, 934 cycles per pixel, 38% more. As a control, an averaging network pools each pair by its mean, with the same parameters and cycles. In restoration the benefit of maxout depends on width: it halved the filters at equal quality in super-resolution [16] and was about 0.04 dB below ReLU in a 64-channel space-to-depth denoiser [17].

**Training and quantization.** We train on 380 Train400 [1] images, holding out every 20th for validation, with 40×40 (A) or 50×50 patches, flips, rotations, MSE and Adam (10⁻³, batch 128), halving the rate after 6 epochs without validation gain. B-32 and 45-channel networks train for a fixed 120 epochs, seed 1 on a CPU, seeds 2–3 and the 45-channel network on a GPU. Weights are per-channel symmetric INT8 and activations 7-bit with one scale per map [18], chosen from percentiles on training images. A module that reproduces the board's integer arithmetic in float (rounding, bias units, skip scaling, pooling, 8-bit output) is then fine-tuned for 15 epochs with straight-through gradients and learned scales [20]; its PSNR matches the integer model within 0.001 dB. No checkpoint, learning-rate step or quantization range was chosen on Set12 or BSD68.

## IV. Verification

The RTL was verified in a UVM [21] environment (protocol agents, a predicting scoreboard, coverage and assertions) on Verilator: 69 runs under UVM 1.2 and 46 under IEEE 1800.2-2020 on seven builds (three of them w = 4) passed, and all 15 injected bugs were caught. Shape coverage was 89–100% on a reduced build and 17–29% on the board build; the denoisers' hidden shapes are among its directed CIFAR-10 shapes, and their first and last layers on the board, at w = 1 and 4. On the board every layer's output is compared value by value with the integer model; every board figure passed.

## V. Results

**Setup.** Set12 and BSD68 [22] at σ = 25, with the same noise for every method, clipped and quantized to 7 bits. This input is the CNNs' training distribution but not BM3D's: on unclipped noise BM3D gains 0.03 / 0.26 dB (Set12 / BSD68), and tuning its σ changes it by under 0.1 dB, so Table I lists both. As a CNN reference on the same input we evaluate the public DnCNN-S weights [1] (float, trained on unclipped noise). SSIM [23] ranks our integer models as PSNR does, except for models under 0.03 dB apart. Integer PSNR is that of the integer model, which the board reproduces bit for bit. Between single-seed networks, differences under 0.1 dB are not interpreted.

*Table I. Mean PSNR (dB), SSIM of the 8-bit output and core cost. Cycles are the corrected model; "board" marks networks whose cycles were measured. "3 seeds" rows are means over seeds 1–3. Util.: dense multiplications per 64 × cycles.*

| Model | Cycles/px | Util. | Params | Set12 float / int | BSD68 float / int | SSIM Set12 / BSD68 |
|---------------------------------------------|-------------------|------------|---------------|-------------------------|-------------------------|-----------------------------|
| BM3D [2], clipped input | — | — | — | 29.95 | 28.37 | 0.850 / 0.799 |
| BM3D, unclipped | — | — | — | 29.98 | 28.62 | 0.851 / 0.804 |
| DnCNN-S [1], same input | 9.3k | — | 556k | 30.35 | 28.89 | 0.859 / 0.822 |
| A: 7 × 32 | 1,775 board | 41% | 47k | 29.87 / 29.83 | 28.83 / 28.80 | 0.842 / 0.809 |
| **B + QAT: s2d, 10 × 64** | 1,323 board | 88% | 300k | 30.13 / **30.12** | 29.01 / **29.02** | **0.855** / **0.821** |
| **B-32 maxout + QAT**, seed 1 | 675 board | 87% | 152k | 30.00 / **30.00** | 28.95 / **28.94** | **0.851** / **0.817** |
| B-32 maxout + QAT, 3 seeds | 675 | 87% | 152k | 29.98 / 29.97 | 28.93 / 28.92 | 0.850 / 0.816 |
| B-32 ReLU + QAT, 3 seeds | 669 | 45% | 76k | 29.79 / 29.82 | 28.81 / 28.82 | 0.846 / 0.812 |
| 10 × 45 ReLU + QAT (s2d) | 934 | 62% | 150k | 30.07 / 30.05 | 28.98 / 28.97 | 0.852 / 0.817 |

![Fig. 2](../denoise/figures/psnr_vs_cycles_en.png)

*Fig. 2. Integer PSNR against core cycles per pixel (left Set12, right BSD68). Filled: board-measured cycles. B-32: three seeds each, drawn apart in x.*

**Quality model.** B + QAT reaches 30.12 / 29.02 dB: +0.17 / +0.66 dB over BM3D (+0.14 / +0.40 dB unclipped) and +0.29 / +0.22 dB over A on all 80 images, in 1.34× fewer cycles.

**Speed model.** B-32 + maxout + QAT (seed 1) takes 2.63× fewer cycles than A for 30.00 / 28.94 dB, +0.17 / +0.14 dB above A: level with BM3D on Set12 (9/12 images), and +0.57 dB on BSD68 (+0.32 dB unclipped). Without pooling, B-32 matches A on average (29.82 / 28.82 dB) in 2.66× fewer cycles.

**Free channels against ReLU, and max against mean.** Over three seeds maxout averages +0.15 / +0.10 dB above the same-width ReLU network for 1.01× the board cycles, but the seeds disagree (+0.37 / +0.26, −0.03 / −0.02 and +0.10 / +0.07 dB; image-paired SE ≤ 0.04 dB), so by the rule set before seeds 2 and 3 (every maxout seed above every ReLU seed) we do not claim pooling denoises better. Seed 1's gap was inflated by a collapse of its ReLU run; such collapses hit four of the nine 120-epoch runs, of every kind, and in each network the collapsed runs scored lowest (averaging: float Set12). The 45-channel ReLU network (maxout's parameter count) scored 30.05 / 28.97 dB (one seed), above all six 32-channel runs, for 1.38× the cycles. Averaging the pairs was within 0.1 dB of maxout (seed 2 integer; seed 1 float validation and Set12 only).

**Quantization and the same-input reference.** QAT brought every ReLU and maxout model within 0.04 dB of its float version; before it they had lost up to 0.25 dB. On the same input DnCNN-S (556k, float) beats our 300k integer model by 0.2 dB on Set12 and in SSIM on both sets (by 0.001 on BSD68); its BSD68 PSNR deficit reflects training on unclipped noise.

**Board.** The maxout layers (K = 288, 64 outputs) took 289 cycles per window, like the 32-output layers of A and the ReLU network: doubling the outputs cost no core cycles at w = 1 (Table II). Throughput is low: at 50 MHz, 0.9–2.3 s of core time per 256×256 image (0.27–0.90 s at w = 4), against 30–38 ms for float PyTorch on a 4-core CPU. The JTAG harness dominates wall-clock time, and the on-chip ARM was not compared.

*Table II. Board runs (Set12 05.png, 256×256, 50 MHz, no mismatch in any layer). Cycles per window: model → board; B-32 networks with QAT; three earlier versions also matched. w = 4: cycles per pixel.*

| Model | Hidden K / COUT | Cycles/window | w = 4 |
|---------------------|----------------------------|----------------------|-------------|
| A | 288 / 32 | 288 → 289 | 573 |
| B + QAT | 576 / 64 | 576 → 577 | 683 |
| B-32 maxout | 288 / **64** | 288 → **289** | 503 |
| B-32 ReLU | 288 / 32 | 288 → 289 | 203 |

## VI. Conclusion

On a 64-multiplier integer core, a cycle model that matches the board showed that the bottleneck is the input port, not the multipliers, and two choices that look wasteful by FLOP count became cheap: space-to-depth fitted a 6.4× larger network into 25% fewer cycles, and doubling the hidden outputs and pooling them in pairs doubled the parameters for 1% more cycles, though its gain over the same-width ReLU network did not hold in every seed. These rules belong to an input structure fed by host-built windows, but the test behind them should carry over: by the cycle model about P·T/w output channels are free, so pooling 64 outputs would again be free on a core of this organization with 256 multipliers fed four values per cycle, and would not be on this core at two. EfficientNet-X [5], HALP [12] and DRACO [13] apply the same logic on TPUs, GPUs and systolic arrays. On this core at w = 4 the board matched the count behind it; elsewhere P·T/w is still a prediction. At w = 1 pooling is free in cycles only: it issued 3.0× the ReLU network's nonzero multiplications. Energy, end-to-end time without the test harness, other noise levels and color images are not reported. Code, models and board logs are in the repository.

**Acknowledgment.** This study was conducted with the support of the Ministry of Science and ICT and the Institute for Information & Communications Technology Planning & Evaluation (IITP) under the 'SW-oriented University Program.'

## References

[1] K. Zhang, W. Zuo, Y. Chen, D. Meng, and L. Zhang, "Beyond a Gaussian denoiser: Residual learning of deep CNN for image denoising," *IEEE Trans. Image Process.*, vol. 26, no. 7, pp. 3142–3155, 2017.

[2] K. Dabov, A. Foi, V. Katkovnik, and K. Egiazarian, "Image denoising by sparse 3-D transform-domain collaborative filtering," *IEEE Trans. Image Process.*, vol. 16, no. 8, pp. 2080–2095, 2007.

[3] S. Williams, A. Waterman, and D. Patterson, "Roofline: An insightful visual performance model for multicore architectures," *Commun. ACM*, vol. 52, no. 4, pp. 65–76, 2009.

[4] N. Ma, X. Zhang, H.-T. Zheng, and J. Sun, "ShuffleNet V2: Practical guidelines for efficient CNN architecture design," in *Proc. ECCV*, 2018.

[5] S. Li, M. Tan, R. Pang, A. Li, L. Cheng, Q. V. Le, and N. P. Jouppi, "Searching for fast model families on datacenter accelerators," in *Proc. CVPR*, 2021, pp. 8085–8095.

[6] Z. Du, J. Liu, J. Tang, and G. Wu, "Anchor-based plain net for mobile image super-resolution," in *Proc. CVPRW*, 2021, pp. 2494–2502.

[7] D. Wang, K. Xu, and D. Jiang, "PipeCNN: An OpenCL-based open-source FPGA accelerator for convolution neural networks," in *Proc. FPT*, 2017.

[8] C.-T. Huang, Y.-C. Ding, H.-C. Wang, C.-W. Weng, K.-P. Lin, L.-W. Wang, and L.-D. Chen, "eCNN: A block-based and highly-parallel CNN accelerator for edge inference," in *Proc. MICRO*, 2019, pp. 182–195.

[9] W. Kang et al., "Improvement and hardware design of image denoising algorithm based on deep learning," in *Proc. ICICM*, 2024, pp. 671–676.

[10] L. Tu, Y. Gu, X. Huang, and X. Wu, "Lightweight design of image denoising based on TNet mini," in *Proc. AIIM*, 2024, pp. 646–649.

[11] C. Li, C. Bled, R. Fernandez, and S. Shanker, "ReTiDe: Real-time denoising for energy-efficient motion picture processing with FPGAs," in *Proc. CVMP*, 2025.

[12] M. Shen, H. Yin, P. Molchanov, L. Mao, J. Liu, and J. M. Alvarez, "Structural pruning via latency-saliency knapsack," in *Proc. NeurIPS*, 2022.

[13] N. K. Jha, S. Ravishankar, S. Mittal, A. Kaushik, D. Mandal, and M. Chandra, "DRACO: Co-optimizing hardware utilization, and performance of DNNs on systolic accelerator," in *Proc. ISVLSI*, 2020.

[14] K. Zhang, W. Zuo, and L. Zhang, "FFDNet: Toward a fast and flexible solution for CNN-based image denoising," *IEEE Trans. Image Process.*, vol. 27, no. 9, pp. 4608–4622, 2018.

[15] I. J. Goodfellow, D. Warde-Farley, M. Mirza, A. Courville, and Y. Bengio, "Maxout networks," in *Proc. ICML*, 2013.

[16] J.-S. Choi and M. Kim, "Single image super-resolution using lightweight CNN with maxout units," in *Proc. ACCV*, 2018, pp. 471–487.

[17] S. Gu, W. Li, L. Van Gool, and R. Timofte, "Fast image restoration with multi-bin trainable linear units," in *Proc. ICCV*, 2019, pp. 4190–4199.

[18] B. Jacob et al., "Quantization and training of neural networks for efficient integer-arithmetic-only inference," in *Proc. CVPR*, 2018.

[19] X. Wu, R. He, Z. Sun, and T. Tan, "A light CNN for deep face representation with noisy labels," *IEEE Trans. Inf. Forensics Security*, vol. 13, no. 11, pp. 2884–2896, 2018.

[20] S. K. Esser, J. L. McKinstry, D. Bablani, R. Appuswamy, and D. S. Modha, "Learned step size quantization," in *Proc. ICLR*, 2020.

[21] *IEEE Standard for Universal Verification Methodology Language Reference Manual*, IEEE Std 1800.2-2020.

[22] D. Martin, C. Fowlkes, D. Tal, and J. Malik, "A database of human segmented natural images and its application to evaluating segmentation algorithms and measuring ecological statistics," in *Proc. ICCV*, 2001.

[23] Z. Wang, A. C. Bovik, H. R. Sheikh, and E. P. Simoncelli, "Image quality assessment: From error visibility to structural similarity," *IEEE Trans. Image Process.*, vol. 13, no. 4, pp. 600–612, 2004.
