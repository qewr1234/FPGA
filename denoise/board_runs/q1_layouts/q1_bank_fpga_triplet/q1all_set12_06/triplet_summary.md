# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 13,465,669 | 12,400,408 | 12,251,825 | +7.91094 | +9.01436 |
| 2 | 13,465,669 | 12,400,408 | 12,251,831 | +7.91094 | +9.01432 |
| 3 | 13,465,669 | 12,400,408 | 12,251,825 | +7.91094 | +9.01436 |

**Frozen all Conv saving**: +7.91094%.
**Multi-start all Conv saving**: +9.01435%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 11,597,845 | 10,532,584 | 10,384,001 | +9.18499 | +10.46612 |
| 2 | 11,597,845 | 10,532,584 | 10,384,007 | +9.18499 | +10.46607 |
| 3 | 11,597,845 | 10,532,584 | 10,384,001 | +9.18499 | +10.46612 |

**Frozen Conv2–9 saving**: +9.18499%.
**Multi-start Conv2–9 saving**: +10.46610%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 0/0 | 6/0 |
| 3 | 0/0 | 0/0 | 0/0 |

Each hardware run must pass all ten layer integer oracles.
