## V. Discussion and Limitations

### A. What the result says

For a design whose multiplier budget is fixed and whose DSP blocks are spoken
for, the two axes are not interchangeable. They buy the same throughput -- 5.1%
apart at 64 multipliers -- and one of them costs 35% fewer LUTs and 61% fewer
flip-flops per multiplier. The reason is structural rather than incidental, and
it is visible in the utilisation: the output datapath is sized by the number of
output channels in flight, so spreading multipliers across taps adds arithmetic
without widening it.

This runs against the conventional choice. Ma et al. reject the kernel and
input-channel axes because kernels are small and their size varies between
layers [1], [2], and accelerators built on their analysis unroll the feature-map
and output-channel loops instead. Under activation sparsity neither reason
applies: the tap stream spans 576 positions, and its imbalance comes from the
data rather than from a mismatch between layers. The rejected axis turns out to
be the cheaper one here.

Two results point the same way from different directions. The LUTRAM relation of
Section IV-C is measured independently of the slope in Section IV-B, and both
say the cost is carried by *P*.

### B. Limitations

*One layer.* Every measurement uses `features.3` of VGG11. The resource figures
are properties of the architecture and do not depend on the layer, but the cycle
comparison does: it depends on the nonzero rate and on how evenly the nonzero
taps fall across banks. A layer with a more skewed pattern would narrow the
margin, and one with more uniform sparsity would widen it.

*Static assignment forgoes load balancing.* This is the mechanism by which that
would happen. The cost is measured here (1.16x at *T* = 4, 1.35x at *T* = 8) but
only on one distribution. Bank-balanced approaches [3], [4] remove the imbalance
by pruning the weights into a hardware-friendly pattern; that option is not
available for activation sparsity, where the nonzero positions are not known
until inference, which is why a static hash is used and its cost paid.

*The equal-multiplier pair is synthesis-only.* v3 at *P* = 64 and v4 at *P* = 16,
*T* = 4 were placed and routed but not run on the board; the hardware
measurement is of v3 at *P* = 8. The cycle figures for those configurations come
from the verified cycle model, which agreed exactly with hardware at the point
where both exist, but that is an argument by extension.

*v3's slope rests on two points.* Only two DSP-free configurations of v3 were
built, so 138.5 LUTs per multiplier is a line through two measurements. v4's
three points are consistent to within 4.0%, but the same check cannot be made on
v3.

*The methodology is not new.* Comparing at a fixed multiplier count is the
premise of [1] and [2], stated here so that the contribution is not mistaken for
one.

### C. Scope

The cores implement convolution with bias and ReLU at window level. Pooling,
normalization and the classifier are not in hardware, and requantization between
layers is done by the host. The accelerator is a layer engine, not a complete
network, and the numbers should be read as such.

## VI. Conclusion

Given a fixed number of multipliers on a device with no DSP blocks to spare, a
sparse convolution accelerator can spend them on output channels or on banks of
nonzero taps. Measured after place and route on an XC7Z020, the second costs
89.8 LUTs and 43.8 flip-flops per multiplier against 138.5 and 111.6 for the
first, while the two are within 5.1% of each other in cycles per window at 64
multipliers. The saving comes from sharing one accumulator behind an adder tree
instead of replicating an accumulator per channel, and the utilisation data
confirms the mechanism independently: distributed RAM tracks the number of
output channels in flight, not the number of multipliers.

The axis this favours is the one dense-accelerator analyses set aside, for
reasons that do not carry over to a sparse tap stream. The cycle model behind
the comparison was validated on hardware: over 1,024 windows the measured count
matched simulation exactly with both stall counters at zero, and a complete
112 x 112 feature map reproduced 1,605,632 outputs without a mismatch.
