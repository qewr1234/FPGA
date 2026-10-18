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
