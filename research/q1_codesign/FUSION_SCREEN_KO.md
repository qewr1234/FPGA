# Q1 공동최적화 연구 — 2-Layer Tile Fusion 비용 스크린

**PC:** Vivado가 없는 RTX 4060 Ti Windows PC에서 실행 가능. Python 3.9, NumPy, 기존 INT8 Export 사용. GPU 학습과 FPGA 프로그래밍은 실행하지 않음.

## 실행 (Windows CMD)

```bat
cd /d C:\fpga\FPGA
git status
git pull origin main
RUN_GPU_Q1_FUSION.cmd
```

로컬 파일에 수정사항이 있다면 먼저 보존하세요. 결과는 `build/q1_fusion_screen/candidates.csv`, `summary.json`입니다.

다른 조건으로 다시 실행:

```bat
python scripts\q1_fusion_cost.py --image-size 256x256 --tiles 16,24,32,40,48,56,64,80,96 --buffer-safety-factor 1.25 --reserve-bram36 16
python scripts\q1_fusion_cost.py --image-size 256x256 --buffer-sets 2 --out build\q1_fusion_double_buffer
```

## 분석 대상

- 실제 QAT INT8 Export `dn_d10_c32_us_fx_qat`의 `conv2+conv3`, `conv4+conv5`, `conv6+conv7`, `conv8+conv9`.
- 원본 256×256 영상에서 Pixel Unshuffle를 거치면 128×128 Feature Map이므로 **Tile T는 원본 영상 기준이 아니라 128×128 내부 격자 기준**.
- Conv B 출력 Tile의 Conv A 계산은 반경 1의 출력 Halo, 첫 레이어 입력은 반경 2의 입력 Halo를 필요로 한다. 타일 간 중복 입력과 추가 MAC을 셈.
- 원래 호스트는 매 레이어 입력을 im2col로 펼쳐서 FPGA에 전송하고 INT32 출력을 수신. 새 아키텍처는 원본 Feature Map을 타일로 DDR에서 읽은 다음 온칩 Window Generator를 통해 펼치고, Conv A 결과를 온칩에서 재양자화한 후 B에 넘긴다고 가정.

## HW 자원 가정

- Vivado 2026.1 기존 W=4 설계 전체: 68 RAMB36 + 6 RAMB18 = **RAMB36 71블록 환산**. XC7Z020 전체는 140 RAMB36 환산.
- 기본으로 새 로직을 위해 RAMB36 16블록을 예비하고, 입력·중간 버퍼 계산 크기에 안전 계수 1.25를 적용.
- 입력 Tile 버퍼 약 `(T+4)^2 * C_in` 바이트, Conv A 7비트(실제 uint8 저장) 출력 버퍼 약 `(T+2)^2 * C_mid` 바이트. 최종 B INT32는 DMA 전송 가정.
- Full-Tile 버퍼 1벌이 기본. 더블버퍼는 `--buffer-sets 2`로 스크린.
- BRAM36 1블록의 원시 용량 4608바이트에 의한 **용량 프록시**이고, 실제 BRAM 포트·뱅킹·LUT·WNS·경합과 데이터 파이프라인을 반영하지 않음.

## 지표 해석 및 한계

- `baseline_external_bytes`: 현재 구조에서 A+B 두 층의 W=4 입력 Window와 INT32 반환 데이터의 논리적 합계. 실제 DDR 버스 계수 측정값 아님.
- `proposed_external_bytes`: 온칩 Window Generator와 Conv A 재양자화 및 중간 버퍼가 **새로 구현되었다고 가정**한 경우의 입력 Tile 전송과 Conv B의 INT32 반환 총합.
- `external_stream_reduction_pct`: 두 가정의 스트림 바이트 차이. **실제 FPGA 속도, 처리량, 전력 절감이 아님.**
- `extra_mac_pct`: Conv A Halo 중복으로 인한 추가 MAC 비율. 공유 코어는 새 구조에서 여전히 A와 B를 직렬로 실행해야 하므로 시간이 늘 수 있음.
- `bram_proxy_fit`: BRAM36 환산 용량을 만족할 가능성이 있는지 보는 예비 검사로, Vivado 합성 성공을 보장하지 않음.
- `pareto_tiles`: 추정 데이터 전송량과 MAC 연산량에만 대한 Pareto 후보. 실제 전체 지연 최적점 아님.
- 기본 CPU `im2col` 시간이 작으므로 **컴퓨트 병목이 크면 전체 처리속도는 개선되지 않을 수 있음**.

## 검증

`scripts/q1_fusion_selftest.py`가 서로 다른 크기의 Tile에 대해 Synthetic Integer Conv와 실제 QAT 가중치의 `conv2+conv3`를 비교한다. 전체 영상과 타일 연산의 **모든 INT32 원소가 정확히 일치**해야 통과.

이 검증은 어디까지나 CPU Oracle 검증. 실제 RTL Window Generator, 누산기, FPGA 온칩 재양자화(특히 NumPy의 `rint`와 반올림 규칙 일치), PS7/DDR, AXI DMA, 지연, 주파수, 전력은 아직 검증하지 않았다.

## 다음 하드웨어 연구 Gate

1. Smart ZYNQ SL 보드 DDR/MIO 프리셋을 검증하고 기존 W=4 보드를 재현.
2. 진짜 호스트 / DMA / PL / 재양자화 소요시간을 분해 측정.
3. 제안 Tile에 필요한 RTL 구성요소의 합성·배치배선 및 bit-exact 검증.
4. Baseline과 동일한 정밀도·이미지·클럭·동급 자원을 맞추고 실제 전체 지연, DDR 전송, 전력을 비교.
5. 비트 일치 구조가 완성된 후 QAT 모델 간 화질과 실제 하드웨어 비용의 공동 최적화 수행.

**현재 이 실험은 Q1 신규성의 증명이 아니라, 구현 위험과 탐색 공간을 줄이는 사전 비용 분석이다.**
