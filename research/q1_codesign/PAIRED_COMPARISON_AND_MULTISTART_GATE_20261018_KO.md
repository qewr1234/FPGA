# Bank-aware channel permutation: paired statistics, model selection and release gate (2026-10-18)

**Data origin:** user-uploaded paired_tests.json and PAIRED_STATS.md from 612 image-noise conditions. Paired sampling unit is each of the 68 BSD68 image IDs, preserving 3 sigmas and 3 AWGN seeds within each image. These values are **modeled W4 sparse Conv2-Conv9 core-cycle coefficients, not FPGA physical measurements**.

## Key paired comparisons (68 image clusters)

| Comparator (Multi-start minus other method) | Overall paired gain (pp) | Descriptive 95% image bootstrap CI (pp) | Multi-start better on |
|---|---:|---|---|
| Frozen_01 | +0.584153 | [+0.516437, +0.651236] | 67 / 68 images |
| Greedy | +0.319633 | [+0.290750, +0.349208] | 68 / 68 |
| Annealing | +0.196345 | [+0.157002, +0.234890] | 58 / 68 |
| Risk-aware greedy | +0.414090 | [+0.356248, +0.471108] | 66 / 68 |
| Density sorting | +8.005877 | [+7.889320, +8.134093] | 68 / 68 |

Pooled modeled gain vs identity: Multi-start 10.708853%, Frozen_01 10.124700%, Annealing 10.512508%, Greedy 10.389220%, Density 2.702976%. Do not interpret ±0.584pp as an extra 0.584% speedup in physical board execution.

### Noise-distribution interaction

| Sigma | Multi-start saving | Frozen saving | Paired improvement pp (Multi-start − Frozen) | 95% descriptive CI | Better images |
|---|---:|---:|---:|---|---|
| 15 | 8.264314% | 7.007236% | +1.257079 | [+1.135075, +1.377535] | 67/68 |
| 25 | 9.524899% | 8.779397% | +0.745502 | [+0.648285, +0.850877] | 65/68 |
| 50 | 13.891984% | 14.037079% | **−0.145094** | [−0.205003, −0.083979] | 17/68 |

**Conclusion:** Multi-start is a strong pooled core coefficient candidate, but it is **not uniformly optimal**: the previous Frozen channel mapping outperforms at σ50. It is invalid to choose the better group after looking at heldout BSD68 results and call the result an unbiased adaptive scheduler. If a sigma-aware method is proposed, selection must be based on calibration data and supported by an independent test.

No correction for the number of comparisons was applied. The two-sided sign-test p-values and cluster bootstrap intervals are exploratory and represent limited image population/known architecture; they do not establish hardware acceleration or algorithm novelty.

## Next practical deliverable: REAL multistart INT8 export (not just virtual bank grouping)

Commit on GitHub:

- `RUN_GPU_Q1_MULTISTART_EXPORT.cmd`: one command entrypoint.
- `scripts/q1_multistart_finalize.py`: confirms optimizer config / exported output channel permutation / full 720 conditions / SHA256 before packaging.

### GPU PC command

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_GPU_Q1_MULTISTART_EXPORT.cmd
```

**The command never reruns multi-start optimization, and never overwrites the original exported model.** It consumes the original GPU run's:
`build/q1_gpu_deadline_full/export_multistart_greedy.json`,
`method_config.json`, and `summary.json`.

1. Calls the existing `scripts/q1_reviewer_export.py` to reorder the actual original ReLU QAT INT8 weights/bias/requant tables, outputting `build/q1_multistart_export/dn_d10_c32_us_fx_qat`.
2. Checks CPU full-image equivalence for Set12 01.png and 05.png.
3. Runs `scripts/q1_gpu_bitexact_stress.py` against the new exported model on BSD68+Set12, sigma15/25/50, seed0/1/2. Requires all **720 image-condition outputs bit-identical**.
4. Final script matches source/current binary SHA256, compares group maps against frozen training results, rejects incomplete tests, and creates:

`build/q1_multistart_verified_export_20261018.zip`

**This ZIP cannot be published to GitHub directly from the agent without the optimized `export_multistart_greedy.json` generated on the user's PC**, because the permutation differs from the earlier fixed `frozen_01` GitHub package. Upload that JSON and the complete stress `summary.json` here; only then can the independently reconstructed multi-start model be released in the repository. GitHub already contains all scripts.

## Paper/engineering verdict

- Source 32-channel ReLU QAT model: one independent QAT physical board A/B pair is needed. Existing bitstream/core ID, clock, sparse mode and PS DDR compatibility require verification.
- Frozen_01 candidate: 720 independent noise-condition GPU output equality was observed in the previous report, but **FPGA W4 speedup is not measured**.
- New multi-start candidate: **do not claim lossless final output before the new export/stress CMD passes.**
- The proposed objective is an optimization over banked activity counts and has similar prior-art ideas; must clarify novel mechanisms and compare matched-complexity optimizer baselines for Q1 contribution.
- “Physical FPGA ~10.709% faster” is an unsupported statement. The correct wording is “Predicted sparse W4 core compute coefficients in Conv2-9 decreased by 10.709% across the chosen image-noise conditions.”
