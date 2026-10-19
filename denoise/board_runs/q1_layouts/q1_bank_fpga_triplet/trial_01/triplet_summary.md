# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 13,289,030 | 12,355,814 | 12,278,419 | +7.02245 | +7.60485 |
| 2 | 13,289,030 | 12,355,814 | 12,278,419 | +7.02245 | +7.60485 |
| 3 | 13,289,030 | 12,355,826 | 12,278,419 | +7.02236 | +7.60485 |

**Frozen all Conv saving**: +7.02242%.
**Multi-start all Conv saving**: +7.60485%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 11,421,202 | 10,487,986 | 10,410,591 | +8.17091 | +8.84855 |
| 2 | 11,421,202 | 10,487,986 | 10,410,591 | +8.17091 | +8.84855 |
| 3 | 11,421,202 | 10,487,986 | 10,410,591 | +8.17091 | +8.84855 |

**Frozen Conv2–9 saving**: +8.17091%.
**Multi-start Conv2–9 saving**: +8.84855%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 12/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
