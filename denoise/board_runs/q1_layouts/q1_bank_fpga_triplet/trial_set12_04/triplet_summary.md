# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 13,455,778 | 12,424,571 | 12,319,430 | +7.66367 | +8.44506 |
| 2 | 13,455,778 | 12,424,571 | 12,319,430 | +7.66367 | +8.44506 |
| 3 | 13,455,778 | 12,424,571 | 12,319,430 | +7.66367 | +8.44506 |

**Frozen all Conv saving**: +7.66367%.
**Multi-start all Conv saving**: +8.44506%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 11,587,953 | 10,556,746 | 10,451,605 | +8.89896 | +9.80629 |
| 2 | 11,587,953 | 10,556,746 | 10,451,605 | +8.89896 | +9.80629 |
| 3 | 11,587,953 | 10,556,746 | 10,451,605 | +8.89896 | +9.80629 |

**Frozen Conv2–9 saving**: +8.89896%.
**Multi-start Conv2–9 saving**: +9.80629%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 0/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
