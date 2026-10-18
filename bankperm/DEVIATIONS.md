# Where carrying out PROTOCOL.md needed a choice

PROTOCOL.md, `bounds.py` and `bounds.json` are unchanged (commit c2299e2).
One point of the protocol could not be applied word for word. What was done
instead is below.

## 1. `fit_group` "as written" cannot run on the 45-channel network

PROTOCOL.md fixes the search as `scripts/q1_reviewer_bank.fit_group` as written.
It also says that for C_in = 45 the bank of tap s*45 + p is (s + p) % 4, and that
the class sizes are those of the identity layout (12/11/11/11). `fit_group`
cannot be applied to that layer in two ways:

- it raises `ValueError` when the channel count is not a multiple of 4;
- its objective (`q1_reviewer_bank.cycles`) puts every tap of a channel in the
  channel's class (`counts[:, group == i]`). That is the bank only when
  C_in % 4 == 0. For C_in = 45 the taps of one channel at the nine 3x3 positions
  land in all four banks.

**What was done.** `bankperm/fit.py` `fit_general` is the same search: the same
identity start (`arange(C) % 4`), the same 400 proposals drawn with the same
generator calls in the same order, the same swap of two channels of different
class, and the same acceptance rule (objective lower by more than 1e-10), with
seed 42 + fitted-layer index. Its objective is the protocol's: the mean W=4
window cycles, where each tap's bank is ((s*C_in) % 4 + p % 4) % 4.

**Checks.**

- On every fitted layer of the nine networks with C_in % 4 == 0 (69 layers),
  `fit_general` gives the same groups and the same final objective as
  `fit_group` itself. Those nine networks use `fit_group`'s result, encoded by
  `encode_order`.
- On every fitted layer of all ten networks (77 layers), the objective is
  equal window by window to `predict_w4.window_cycles` on the column-permuted
  calibration windows. This was checked at W = 1, 2 and 4, for the identity, the fitted and
  one random layout.

**Order encoding for unequal classes.** `q1_reviewer_bank.encode_order` also
requires equal classes. For 45 channels the channels of class r, in increasing
original index, fill the positions p with p % 4 == r in increasing order. For
equal classes this is exactly `encode_order` (checked on all 69 layers). For
C_in = 45 the order within a class does not change any count, because the bank
of a tap depends only on p % 4.

Nothing else was chosen. The calibration windows, the generator, the seeds, the
step count and the evaluation follow PROTOCOL.md. On B-32 ReLU s1 the fit
reproduces the published Frozen groups exactly (H0), so no substitution was
needed.
