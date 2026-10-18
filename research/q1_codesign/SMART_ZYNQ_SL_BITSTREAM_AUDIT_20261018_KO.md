# Smart ZYNQ SL W4 bitstream: physical-board safety gate (2026-10-18)

현재 실제 FPGA 로드는 수행하지 않았다. 이 문서는 PC 내부 파일만 확인하는 절차다.

## 사용자 PC에서 발견한 Bitstream

| 폴더 | 판정 |
|---|---|
| build/zed_v3_p8_t4_1789907417/ | legacy W1 candidate, 미확인 |
| build/zed_v4_p16_t4_1790095039/ | legacy W1 candidate, 미확인 |
| build/zed_v4_p16_t4_1792233969/ | legacy W1 candidate, 미확인 |
| build/zed_v4_p16_t4_w4_1792234898/ | W4 파일명 후보, Smart board 호환 미검증 |

중복 system.runs/impl_1/system_wrapper.bit 파일도 발견됨. 동일 명칭이 지원 보드의 유효성을 보장하지 않음.

## 확인된 코드상 문제점

- scripts/build_zedboard.tcl 기본 보드 설정 = em.avnet.com:zed:part0:1.4.
- 설치된 ZedBoard preset이 없으면 같은 XC7Z020 device의 다른 board preset으로 자동 fallback할 수 있음. 같은 FPGA chip은 같은 DDR/MIO configuration을 의미하지 않음.
- 빌드 폴더 zed_v... 접두사는 코드가 자동으로 붙이므로 그 이름만으로 실제 적용된 board preset을 확정할 수 없음. 기존 W4 후보는 현재 검증이 필요.
- scripts/run_board_xsdb.tcl의 loadhw/ps7_init는 PS DDR controller, MIO, clocks를 설정함. board mismatch는 실패/오동작을 유발할 수 있으므로 호환성 확인 전 물리 실행 금지.
- 기존 BOARD_KO.md 중 동일 device라면 바로 사용할 수 있다는 취지의 설명은 Smart ZYNQ SL 호환성 검증을 대체하지 못함.
- scripts/q1_fpga_triplet.py가 zed_v/zedboard 이름의 빌드를 물리 실험에서 거부하도록 설계된 것은 의도된 안전장치임. 폴더명 변경으로 우회하면 안 됨.

## read-only 점검 명령 (보드 프로그래밍 없음)

Windows CMD:

~~~bat
cd /d C:\fpga\FPGA
set "B=C:\fpga\FPGA\build\zed_v4_p16_t4_w4_1792234898"
dir /s /b "%B%\*.xpr"
dir /s /b "%B%\*.bd"
dir /s /b "%B%\*ps7_init.tcl"
dir /s /b "%B%\*.xsa"
~~~

우선 실제 파일 위치를 찾고, 그 뒤 프로젝트의 processing_system7_0 PS DDR part, data bus width, timing, PS reference oscillator, MIO map, PS DDR address space, GP0/HP0, PL FCLK와 reset을 실제 Smart ZYNQ SL PCB revision 및 제조사 회로도와 비교해야 한다.

확인용 파일은 PC에서 찾은 system.xpr, system.bd, ps7_init.tcl의 복사본이다. 현재 이 파일들의 내용은 제출되지 않았으므로 보드 호환을 승인할 수 없다.

참고 자료:
- Smart ZYNQ SL 제품 페이지, XC7Z020 board: https://www.exaontech.com/products/z7nano-fpga
- 유통되는 Smart ZYNQ SL schematic 2023-05 (DDR3 MT41K256M16, x16 표기): https://es.scribd.com/document/688578226/Smart-ZYNQ-SL-Schematic-20230510
- Avnet Zynq PS Preset and Board Definition Files: https://www.avnet.com/wcm/connect/873d91e3-399f-48b6-aac2-cddc272dc0e7/Zynq+PS+Preset+(TCL)+and+Vivado+Board+Definition+Files.pdf

단, 실제 보드 리비전은 유통 문서와 다를 수 있으니 보드 PCB 실크·칩 마킹·스키매틱 대조 전에는 이 사양을 확정 사실로 사용하지 않는다.

## 실제 보드 승인 조건

1. Smart ZYNQ SL용 정합된 PS7 preset으로 신규 프로젝트 생성. 임의의 다른 board-part fallback 금지.
2. RTL W4/T4/P16, 모든 Conv 레이어 대상 충분한 K_MAX/COUT_MAX, PS↔AXI DMA↔PL 설정과 50MHz FCLK를 검증.
3. PS DDR/MIO/PLL 초기화, 실제 DDR write/read, JTAG 경로 검증. PS reference clock과 PL oscillator 50MHz를 혼동하지 않기.
4. FPGA 보드와 설정이 일치하는 독립적 확인이 끝난 뒤에만 RUN_FPGA_Q1_TRIPLET.cmd 실행.

실제 FPGA A/B/C 실측까지 완료되면 예상 저장 위치 (현재 생성되지 않음):

- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json
- C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.md

**현재 상태: bitstream–board compatibility NOT VERIFIED. Do not program legacy build.**
