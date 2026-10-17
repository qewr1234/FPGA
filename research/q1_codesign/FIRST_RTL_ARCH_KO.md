# Q1 Stage 2: 첫 RTL 프로토타입의 하드웨어 계약 — conv2→conv3, T=32

> 상태: **설계 초안이며 아직 RTL을 구현하거나 검증한 결과가 아님.**
> 근거: 2026-10-18 업로드한 `candidates.csv` / `summary.json`, `scripts/q1_fusion_cost.py` 분석.

## 1. 목표와 기각 조건

- 기존 `dn_d10_c32_us_fx_qat` 정수 Export의 `conv2` 및 `conv3`를 연결하는 **공유 W=4 MAC 코어** 기반 Dataflow.
- 256×256 원본 영상 → Pixel Unshuffle 후 **128×128**, 32채널 Feature Map을 처리. 32×32 Tile의 출력 16개.
- 기존과 **동일한 INT32 conv3 출력 전 원소 bit-exact** 보장. PSNR 차이가 0이라도 원소가 다르면 실패.
- 새 구조의 전체 PS/DDR/DMA/PL 실행시간, DDR Bytes, BRAM/LUT/Clock/전력은 모두 미측정. 기존 하드웨어 자원을 넘어가거나 전체 지연 이득이 거의 없으면 기각.

## 2. 알고리즘 / Window / Halo 명세

1. 원본 Conv2의 입력 Feature Map은 `C=32, H=W=128, uint8(0..127)`.
2. Conv3 출력 Tile T×T를 계산하기 위해 Conv2는 T+2 경계 내 출력 (영상 밖 출력은 0 padding), Conv2의 입력 접근 영역은 T+4 경계.
3. 각 Conv2 픽셀의 taps 순서는 기존 RTL Export와 동일한 `(kernel_y, kernel_x, input_channel)`; Conv2/3은 모두 K=288, COUT=32.
4. Stage-A Conv2: 32채널 INT32 `max(0, bias + Σ(weight_int8 * activation_uint8))`. 각 출력 채널의 `requant`를 7비트(0..127)로 포화시키며 NumPy `np.rint`의 ties-to-even을 bit-exact로 재현해야 함.
5. Stage-B Conv3: Stage-A의 7비트 결과를 3×3 Window Generator가 읽어 INT32로 연산. 전체 conv3 출력과 정수 참조 결과를 비트 단위로 비교.
6. 코너/영상 외부의 padding은 **원본 이미지의 전역 경계에서만 0**. Tile 경계를 영상 경계로 잘못 취급해서는 안 됨.
7. 채널 32개 × 3×3 = 288 taps/Window; W=4이면 논리상 72 beat/Window. 실제 코어 계산·입출력 마감 시간은 별도 사이클 실측.

## 3. 처리 단계 — 기존 코어 공유 (초기 구현)

```text
PS DDR feature map (32x128x128 uint8)
     │  DMA / tile with radius-2 halo
     ▼
Tile Input SRAM (nominal 36x36x32 = 41,472 bytes)
     │  On-chip 3x3 window generator (NEW, 4 taps/beat)
     ▼
Existing W=4 MAC core [weights: conv2]
     │  INT32 accumulator output
     ▼
Per-channel INT32→uint7 requant (NEW, bit-exact rounding)
     ▼
Intermediate SRAM (nominal 34x34x32 = 36,992 bytes)
     │  3x3 window generator (NEW)
     ▼
Same W=4 MAC core [weights switched to conv3]
     │  INT32 conv3 tile
     ▼
AXI DMA → DDR
```

- 데이터 흐름 그림은 **목표 구조**일 뿐 기존 RTL에 해당 블록이 존재한다는 뜻이 아님.
- Shared MAC 사용 시 Stage A와 B를 직렬 실행하고, 중간 결과 SRAM은 stage 사이를 보존. 두 병렬 MAC을 가정하지 않음.
- Tile 안에서 layer2→layer3 간 전환 시 **가중치 재적재 및 Config 제어 overhead**가 발생할 수 있음. 현 기존 RTL의 config 저장/호출 인터페이스와 보드 스크립트를 검토 후 구현 결정.

## 4. 32 vs 48 수치 (128×128, conv2+conv3)

| 지표 | T=32 | T=48 |
|---|---:|---:|
| Tile 수 | 16 | 9 |
| 이론적 input+output stream reduction | 80.014% | 80.273% |
| Halo extra MAC | +4.7974% | +3.1738% |
| 추가 BRAM36 환산 (buffer safety ×1.25) | 22 | 46 |
| baseline 71 + reserve 16 기준 잔여 BRAM36 환산 | 31 | 7 |

- 48은 전송량 +34.5KiB(비교 시 T=32가 그만큼 큼), 중복 MAC 약 +4.9M(비교 시 T=32가 그만큼 큼)을 줄이는 반면 24개 BRAM36 환산을 더 사용.
- 32를 **첫 프로토타입**, 24를 자원 부족 시 폴백, 48을 합성 가능할 때 후속 비교 후보로 선택.
- 기존 `pareto_tiles=[48]`은 **BRAM을 목적함수로 넣지 않은 2D Pareto**이므로 32를 제압했다는 의미가 아님.

## 5. 반드시 추가해야 할 비용 항목

기존 후보 CSV는 2개의 레이어에 대해 입력 Window·INT32 출력 데이터 스트림만 계산. 실제 구현에서 아래도 계측/포함:

1. **가중치 재적재**: Conv2 + Conv3 각 32×288 INT32 config + 32 bias = 약 36,992 byte/층. Tile마다 2회 적재면 16×2×36,992 ≈ 1.129MiB의 config 스트림. 기존 각 레이어별 1회(합계 약 72.25KiB)에 비해 추가 전송 및 설정 지연 발생. 모든 Tile에 가중치를 유지·스위칭할 수 있는 메모리 추가 시 BRAM 비용 증가.
2. **DMA/AXI setup**: Tile마다 입출력 DMA 요청·ready/valid stall, setup/flush cycles, PS 측 오버헤드.
3. **Window 생성 속도**: 실제 4 tap/cycle 지속 가능한가? BRAM 포트 충돌/뱅킹/선행 피처 재사용 문제.
4. **Requant 지연과 면적**: INT32 per-channel scale multiply, round-to-nearest-even, saturation. float64 `np.rint`과 Fixed-Point 하드웨어 정확도 검증.
5. **BRAM·LUT·Routing**: 본문의 22 BRAM36은 이상 용량 프록시임. SRAM의 주소/뱅크 분할, writer-reader 경합, timing closure 반영 필요.
6. **보드 호환성**: 기존 build Tcl은 ZedBoard PS/DDR 프리셋이 기본. Smart ZYNQ SL의 DDR/MIO/reset 설정 실증 전 물리보드 실행 금지.

## 6. 검증 Gate

**Gate A, GPU/CPU PC:** 기존 QAT Export의 Conv2→Conv3 정수 Oracle에서 임의 크기/홀수 경계/여러 Tile 전량 bit-exact. 가능하면 원본 입력의 conv1 Feature Map까지 적용.

**Gate B, FPGA PC RTL simulation:** Window Generator 3×3 taps의 실제 순서, global padding, ready/valid throttling, intermediate requant을 기존 SW Oracle 출력과 0 mismatch로 검증.

**Gate C, Vivado 2026.1:** XC7Z020-CLG484 BRAM/LUT/FF/DSP/WNS, 50/100MHz 타이밍, 실제 메모리 및 Controller 자원 보고.

**Gate D, Smart ZYNQ SL:** DDR/MIO 확인 후 동일 이미지·정수 모델·클럭 조건에서 CYCLES + AXI stall + PS/DMA/PL 전체 시간, 반복 측정.

**Gate E, 연구 기여:** 단순 Window Buffer 선행연구 대비 어떤 설계 공간/스케줄링/비용 모델의 기여가 있는지 독립적으로 검증해야 Q1 주장 가능.

## 7. 다음 구현 우선순위

1) FPGA PC: Smart ZYNQ SL DDR/MIO preset와 기존 W=4 build 동작 확인.
2) 독립적인 3×3 Window Generator RTL 및 CPU 정수 Oracle와 비교하는 테스트벤치.
3) On-chip per-channel requantizer의 bit-exact testbench.
4) Tile Controller와 Shared MAC의 stage switch (가중치 재적재 포함).
5) conv2+conv3 32×32 end-to-end bit-exact 구현 및 보드 계측.

상기 모두 **측정/검증 전에는 속도향상·전력절감·Q1 신규성 확보를 주장하지 않는다**.
