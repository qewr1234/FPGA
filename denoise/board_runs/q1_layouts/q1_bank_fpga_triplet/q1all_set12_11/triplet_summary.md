# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 52,664,826 | 49,206,545 | 48,861,314 | +6.56659 | +7.22211 |
| 2 | 52,664,826 | 49,206,545 | 48,861,308 | +6.56659 | +7.22212 |
| 3 | 52,664,826 | 49,206,545 | 48,861,308 | +6.56659 | +7.22212 |

**Frozen all Conv saving**: +6.56659%.
**Multi-start all Conv saving**: +7.22212%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 45,193,674 | 41,735,393 | 41,390,162 | +7.65214 | +8.41603 |
| 2 | 45,193,674 | 41,735,393 | 41,390,156 | +7.65214 | +8.41604 |
| 3 | 45,193,674 | 41,735,393 | 41,390,156 | +7.65214 | +8.41604 |

**Frozen Conv2–9 saving**: +7.65214%.
**Multi-start Conv2–9 saving**: +8.41604%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 6/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 0/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
