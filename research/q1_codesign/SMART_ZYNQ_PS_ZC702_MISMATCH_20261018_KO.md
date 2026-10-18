# 정정 (2026-10-18): 기존 W4 FPGA의 실제 정상 작동 기록 확인

**이 문서의 원래 "ZC702 BoardPart 설정이므로 무조건 기존 W4 비트스트림을 사용하지 말고 새로 빌드해야 한다"라는 결론은 과도했다.** 실제로 GitHub에 다음 과거 보드 실측 근거가 저장돼 있다.

- `denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json`: `emulated=false`, sparse W4 mode=1, Core ID `0x4d410303`, 50 MHz, **13,289,042 cycles**, 원본 INT8 Oracle 불일치 **0**(Conv1~10).
- `denoise/w4_measured.json`: 해당 W4 원본의 사이클 및 stall 집계 일치, W1 대비 **3.2968×**.
- 과거 W4 실행기 `RUN_W4_DENOISE.cmd`는 실제 `build/zed_v4_p16_t4_w4_*` 비트스트림을 사용해 수행하도록 되어 있다. 따라서 폴더명에 `zed_v`가 있다는 이유만으로 사용 불가 판정해서는 안 된다.

**남은 사실상의 공백:** 이 역사적 보드 실측 보고서는 사용 당시 **.bit SHA256을 기록하지 않았다**. 따라서 현재 로컬 폴더에 있는 후보가 그때 사용한 비트스트림과 *바이트 단위로 동일하다*고 자동 확정할 수는 없다. 또한 ZC702 프리셋과 실물 Smart ZYNQ SL DDR/MIO 일치성은 별도 확인이 필요하다.

**다음 절차는 재빌드가 아니라 증거 연결부터:** `RUN_FPGA_Q1_W4_PROVENANCE.cmd`로 과거 실측을 자동 재검증하고, 현재 W4 .bit의 SHA256을 오프라인으로 기록한다. 실제 보드에서 동일 바이너리가 성공했다는 사실을 독립 검증한 경우 그 근거로 사용 가능하다. 모델 3종 실제 실험에는 별도의 승인 및 동일 비트스트림 검증이 필요하며, 감사 도구는 FPGA를 프로그래밍하지 않는다.

기존 본문에 나온 DDR 불일치 분석은 **Vivado 프로젝트 설정 차이의 사실**로만 읽어야 한다. 이를 실제 하드웨어의 실패 사실이나 무조건적인 전면 재빌드 요구로 해석하지 말 것.

---

# Smart ZYNQ SL PS/DDR review: confirmed ZC702 preset mismatch

Date: 2026-10-18. Audited from user-uploaded Q1_SMART_ZYNQ_PS_REVIEW.zip containing system.xpr, system.bd, ps7_init.tcl (CRC passed).

## Verified facts, from the three uploaded design files
- Actual Vivado project uses BoardPart xilinx.com:zc702:part0:1.4 and DSABoardId zc702, **not Smart ZYNQ SL**. FPGA part xc7z020clg484-1, Vivado 2026.1.
- PS DDR preset part MT41J256M8 HX-15E, DDR3 533.333 MHz, RAM high address 0x3FFFFFFF (1GiB mapping).
- ZC702 board memory is 1GiB DDR3 32-bit, using 4 × 256Mx8 parts; public Smart ZYNQ SL 1.3B design describes 512MB DDR3 x16 using one MT41K256M16TW-107. The user's actual PCB revision and DDR chip are still unverified.
- PS FCLK_CLK0 is **100MHz** (PCW_FPGA0_PERIPHERAL_FREQMHZ=100), while the controlled FPGA A/B/C protocol requests 50MHz.
- MIO: QSPI 1..6, SDIO0 40..45, UART1 48..49, ENET0 16..27 (ZC702 mapping, must not assume the Smart board uses it).
- PS M_AXI_GP0 and S_AXI_HP0 enabled; AXI DMA 32-bit MM2S/S2MM streams and window_mac_top connected; DMA control 0x40400000 and MAC core 0x43C00000.
- The Vivado block diagram is internally validated. That is NOT physical Smart board hardware compatibility.

## Unsafe and safe actions

**DO NOT run the existing bitstream** build/zed_v4_p16_t4_w4_1792234898/system_wrapper.bit on an unverified Smart ZYNQ SL. Renaming the directory to evade the run script's legacy-board safeguard is not a valid workaround.

**Safe next step:** obtain the physical Smart board PCB revision and DDR chip marking; get the exact-revision manufacturer Vivado reference or a PS7 project known to have worked on this exact board. Compare DDR bus width, actual chip timing and drive settings, MIO mapping, reference clock, FCLK_CLK0, reset and DDR memory training. Rebuild the W4 core plus existing AXI DMA in a NEW board-specific project; forbid the build scripts' automatic fallback to ZC702/ZedBoard board-part settings. Preserve original 3-model archives.

Do not physically program until PS/DDR/MIO compatibility has been independently established. After board-specific DDR smoke validation, run repeated identical-bitstream 3-model physical timing tests, recording stalls and whole-pipeline latency separately.

## File save paths on the Windows PC

Existing source: C:\fpga\FPGA\build\zed_v4_p16_t4_w4_1792234898\system.xpr

This report, after git pull origin main:
C:\fpga\FPGA\research\q1_codesign\SMART_ZYNQ_PS_ZC702_MISMATCH_20261018_KO.md

Expected future physical results (NOT yet created):
C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.json
C:\fpga\FPGA\build\q1_bank_fpga_triplet\trial_01\triplet_summary.md

## External specification references
- Official ZC702 board guide: https://www.xilinx.com/support/documents/boards_and_kits/zc702_zvik/ug850-zc702-eval-bd.pdf
- Smart ZYNQ SL seller: https://www.exaontech.com/products/z7nano-fpga
- 2023 schematic (may differ from user's PCB revision): https://es.scribd.com/document/688578226/Smart-ZYNQ-SL-Schematic-20230510
- V1.3B module memory information: https://fpga.com.ua/index.php?product_id=369&route=product%2Fproduct
