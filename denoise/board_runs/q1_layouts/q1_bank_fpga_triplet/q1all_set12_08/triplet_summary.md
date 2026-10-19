# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 51,976,970 | 48,895,091 | 48,555,824 | +5.92932 | +6.58204 |
| 2 | 51,976,970 | 48,895,103 | 48,555,824 | +5.92929 | +6.58204 |
| 3 | 51,976,970 | 48,895,091 | 48,555,824 | +5.92932 | +6.58204 |

**Frozen all Conv saving**: +5.92931%.
**Multi-start all Conv saving**: +6.58204%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 44,505,818 | 41,423,939 | 41,084,672 | +6.92467 | +7.68696 |
| 2 | 44,505,818 | 41,423,939 | 41,084,672 | +6.92467 | +7.68696 |
| 3 | 44,505,818 | 41,423,939 | 41,084,672 | +6.92467 | +7.68696 |

**Frozen Conv2–9 saving**: +6.92467%.
**Multi-start Conv2–9 saving**: +7.68696%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 12/0 | 0/0 |
| 3 | 0/0 | 0/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
