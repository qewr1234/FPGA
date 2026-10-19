# Actual physical FPGA W4 core cycle A/B/C measurements

All three models use the same physical W4 core bitstream, clock and image.
These totals include measured PL core cycles and recorded stalls; they are
NOT complete video processing end-to-end latency and NOT energy measurements.

| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 53,752,034 | 49,750,044 | 49,544,363 | +7.44528 | +7.82793 |
| 2 | 53,752,034 | 49,750,044 | 49,544,363 | +7.44528 | +7.82793 |
| 3 | 53,752,034 | 49,750,044 | 49,544,375 | +7.44528 | +7.82791 |

**Frozen all Conv saving**: +7.44528%.
**Multi-start all Conv saving**: +7.82792%.

## Conv2–9 physical cycles
| Rep | Original | Frozen | Multi-start | Frozen saved (%) | Multi saved (%) |
|---:|---:|---:|---:|---:|---:|
| 1 | 46,280,882 | 42,278,892 | 42,073,211 | +8.64718 | +9.09160 |
| 2 | 46,280,882 | 42,278,892 | 42,073,211 | +8.64718 | +9.09160 |
| 3 | 46,280,882 | 42,278,892 | 42,073,223 | +8.64718 | +9.09157 |

**Frozen Conv2–9 saving**: +8.64718%.
**Multi-start Conv2–9 saving**: +9.09159%.

## DMA stall cycles (IN/OUT)
| Rep | Original | Frozen | Multi-start |
|---:|---:|---:|---:|
| 1 | 0/0 | 0/0 | 0/0 |
| 2 | 0/0 | 0/0 | 0/0 |
| 3 | 0/0 | 0/0 | 12/0 |

Each hardware run must pass all ten layer integer oracles.
