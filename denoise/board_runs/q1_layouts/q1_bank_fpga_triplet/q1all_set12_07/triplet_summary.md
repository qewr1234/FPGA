# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 13,412,001 | 12,443,401 | 12,354,313 | +7.22189 | +7.88613 |
| 2 | 13,412,001 | 12,443,401 | 12,354,313 | +7.22189 | +7.88613 |
| 3 | 13,412,001 | 12,443,401 | 12,354,313 | +7.22189 | +7.88613 |

**Frozen all Conv saving**: +7.22189%.
**Multi-start all Conv saving**: +7.88613%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 11,544,177 | 10,575,577 | 10,486,489 | +8.39038 | +9.16209 |
| 2 | 11,544,177 | 10,575,577 | 10,486,489 | +8.39038 | +9.16209 |
| 3 | 11,544,177 | 10,575,577 | 10,486,489 | +8.39038 | +9.16209 |

**Frozen Conv2–9 saving**: +8.39038%.
**Multi-start Conv2–9 saving**: +9.16209%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 0/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
