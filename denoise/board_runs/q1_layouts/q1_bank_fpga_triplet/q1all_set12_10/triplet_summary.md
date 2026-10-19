# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 52,435,842 | 48,849,809 | 48,615,647 | +6.83890 | +7.28547 |
| 2 | 52,435,842 | 48,849,803 | 48,615,647 | +6.83891 | +7.28547 |
| 3 | 52,435,842 | 48,849,803 | 48,615,653 | +6.83891 | +7.28545 |

**Frozen all Conv saving**: +6.83890%.
**Multi-start all Conv saving**: +7.28546%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 44,964,690 | 41,378,657 | 41,144,495 | +7.97522 | +8.49599 |
| 2 | 44,964,690 | 41,378,651 | 41,144,495 | +7.97523 | +8.49599 |
| 3 | 44,964,690 | 41,378,651 | 41,144,495 | +7.97523 | +8.49599 |

**Frozen Conv2–9 saving**: +7.97523%.
**Multi-start Conv2–9 saving**: +8.49599%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 6/0 | 0/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 0/0 | 6/0 |

Each hardware run must pass all ten layer integer oracles.
