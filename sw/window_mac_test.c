/*
 * Zedboard bare-metal driver for window_mac_axis.
 *
 * Streams the quantized VGG11 features.3 windows through the core over AXI DMA,
 * checks every result against the integer oracle, and reports the core's own
 * cycle counter next to the simulated number.
 *
 * Load the blobs produced by scripts/export_board_data.py over JTAG first:
 *   dow -data config.bin 0x10000000
 *   dow -data input.bin  0x10100000
 *   dow -data gold.bin   0x10300000
 *
 * Read the result this way:
 *   MISMATCHES must be 0. If it is not, nothing else in the run means anything.
 *   IN_STALL and OUT_STALL must be 0 for CYCLES to be comparable with
 *   RESULTS_KO.md. A nonzero IN_STALL means the DMA could not keep up and the
 *   run measured the memory path, not the core.
 *
 * Not executed anywhere: no board in the development environment.
 */
#include <stdio.h>
#include "xparameters.h"
#include "xaxidma.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xtime_l.h"

/* Must match the generated window_mac_top and export_board_data.py. */
#define WM_BASE        0x43C00000U
#define K              576
#define COUT           128
#define FRAMES         512
#define MODE_SEQ       2                       /* 0 dense, 1 sparse, 2 alternate */
#define NWINDOWS       ((MODE_SEQ == 2) ? (2 * FRAMES) : FRAMES)

#define ADDR_CONFIG    0x10000000U
#define ADDR_INPUT     0x10100000U
#define ADDR_RESULT    0x10200000U
#define ADDR_GOLD      0x10300000U

#define CFG_WORDS      (COUT * K + COUT)
#define INPUT_WORDS    ((u32)NWINDOWS * K / 4)
#define RESULT_WORDS   ((u32)NWINDOWS * COUT)

/* window_mac_axis register map */
#define REG_CTRL       0x00
#define REG_NWIN       0x04
#define REG_STATUS     0x08
#define REG_CYCLES     0x0C
#define REG_WINDONE    0x10
#define REG_INSTALL    0x14
#define REG_OUTSTALL   0x18
#define REG_OUTCOUNT   0x1C
#define REG_CFGCOUNT   0x20
#define REG_ID         0x24

#define CTRL_CORE_RST  (1U << 0)
#define CTRL_CFG_MODE  (1U << 1)
#define CTRL_MODE_SEQ(m) (((u32)(m) & 3U) << 2)
#define CTRL_ARM       (1U << 4)
#define CTRL_CFG_RESET (1U << 5)

static inline void wm_write(u32 off, u32 v) { Xil_Out32(WM_BASE + off, v); }
static inline u32  wm_read(u32 off)         { return Xil_In32(WM_BASE + off); }

/* The generated xparameters.h spells the DMA id differently across tool versions. */
#ifdef XPAR_AXIDMA_0_DEVICE_ID
#define WM_DMA_ID XPAR_AXIDMA_0_DEVICE_ID
#elif defined(XPAR_AXI_DMA_0_DEVICE_ID)
#define WM_DMA_ID XPAR_AXI_DMA_0_DEVICE_ID
#else
#define WM_DMA_ID XPAR_XAXIDMA_0_BASEADDR
#endif

static XAxiDma dma;

static int dma_init(void)
{
    XAxiDma_Config *cfg = XAxiDma_LookupConfig(WM_DMA_ID);
    if (cfg == NULL) {
        xil_printf("FATAL: no AXI DMA config for device 0\r\n");
        return XST_FAILURE;
    }
    if (XAxiDma_CfgInitialize(&dma, cfg) != XST_SUCCESS) {
        xil_printf("FATAL: AXI DMA init failed\r\n");
        return XST_FAILURE;
    }
    if (XAxiDma_HasSg(&dma)) {
        xil_printf("FATAL: DMA built in scatter-gather mode; rebuild with c_include_sg=0\r\n");
        return XST_FAILURE;
    }
    XAxiDma_IntrDisable(&dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);
    XAxiDma_IntrDisable(&dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
    return XST_SUCCESS;
}

/* Poll one direction to completion. Returns 0 on success. */
static int dma_wait(int to_device, const char *what)
{
    /* The whole run is bounded by a few million cycles; this is generous. */
    volatile u32 guard = 0xFFFFFFFFU;
    while (XAxiDma_Busy(&dma, to_device ? XAXIDMA_DMA_TO_DEVICE : XAXIDMA_DEVICE_TO_DMA)) {
        if (--guard == 0) {
            xil_printf("FATAL: %s DMA did not complete\r\n", what);
            return XST_FAILURE;
        }
    }
    return XST_SUCCESS;
}

static int load_configuration(void)
{
    u32 got;

    /* Core out of reset, stream routed to the cfg port, walker rewound. */
    wm_write(REG_CTRL, CTRL_CFG_MODE | CTRL_CFG_RESET);

    Xil_DCacheFlushRange((UINTPTR)ADDR_CONFIG, CFG_WORDS * 4);
    if (XAxiDma_SimpleTransfer(&dma, (UINTPTR)ADDR_CONFIG, CFG_WORDS * 4,
                               XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS) {
        xil_printf("FATAL: configuration transfer rejected\r\n");
        return XST_FAILURE;
    }
    if (dma_wait(1, "configuration") != XST_SUCCESS) return XST_FAILURE;

    got = wm_read(REG_CFGCOUNT);
    if (got != CFG_WORDS) {
        xil_printf("FATAL: core accepted %lu configuration items, expected %lu\r\n",
                   (unsigned long)got, (unsigned long)CFG_WORDS);
        return XST_FAILURE;
    }
    return XST_SUCCESS;
}

static int run_stream(XTime *elapsed)
{
    XTime t0, t1;

    wm_write(REG_NWIN, NWINDOWS);
    /* Arming clears the input holding register, so arm before the DMA moves. */
    wm_write(REG_CTRL, CTRL_ARM | CTRL_MODE_SEQ(MODE_SEQ));

    Xil_DCacheFlushRange((UINTPTR)ADDR_INPUT, INPUT_WORDS * 4);
    Xil_DCacheInvalidateRange((UINTPTR)ADDR_RESULT, RESULT_WORDS * 4);

    XTime_GetTime(&t0);
    if (XAxiDma_SimpleTransfer(&dma, (UINTPTR)ADDR_RESULT, RESULT_WORDS * 4,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS) {
        xil_printf("FATAL: receive transfer rejected\r\n");
        return XST_FAILURE;
    }
    if (XAxiDma_SimpleTransfer(&dma, (UINTPTR)ADDR_INPUT, INPUT_WORDS * 4,
                               XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS) {
        xil_printf("FATAL: send transfer rejected\r\n");
        return XST_FAILURE;
    }
    if (dma_wait(1, "send") != XST_SUCCESS) return XST_FAILURE;
    if (dma_wait(0, "receive") != XST_SUCCESS) return XST_FAILURE;
    XTime_GetTime(&t1);

    Xil_DCacheInvalidateRange((UINTPTR)ADDR_RESULT, RESULT_WORDS * 4);
    *elapsed = t1 - t0;
    return XST_SUCCESS;
}

static u32 compare_results(u32 *first_bad)
{
    const volatile u32 *got = (const volatile u32 *)ADDR_RESULT;
    const volatile u32 *want = (const volatile u32 *)ADDR_GOLD;
    u32 i, bad = 0;

    for (i = 0; i < RESULT_WORDS; i++) {
        if (got[i] != want[i]) {
            if (bad == 0 && first_bad != NULL) *first_bad = i;
            bad++;
        }
    }
    return bad;
}

int main(void)
{
    XTime elapsed = 0;
    u32 id, cycles, windone, instl, outstl, outcount, bad, first_bad = 0;

    /* Start from the Vitis "Hello World" template and this replaces its main.c;
       platform.c there provides init_platform(). Nothing here needs it. */
    xil_printf("\r\n--- window_mac_axis on Zedboard ---\r\n");

    id = wm_read(REG_ID);
    if ((id & 0xFFFF0000U) != 0x4D410000U) {
        xil_printf("FATAL: ID reads %08lx, expected 4d41000x. Wrong bitstream or base address.\r\n",
                   (unsigned long)id);
        return XST_FAILURE;
    }
    xil_printf("core: %s  K=%d COUT=%d windows=%d\r\n",
               (id & 0xFU) == 3U ? "v4 banked_window_mac" : "v3 overlapped_window_mac",
               K, COUT, NWINDOWS);

    if (dma_init() != XST_SUCCESS) return XST_FAILURE;
    if (load_configuration() != XST_SUCCESS) return XST_FAILURE;
    xil_printf("configuration loaded: %lu items\r\n", (unsigned long)CFG_WORDS);

    if (run_stream(&elapsed) != XST_SUCCESS) return XST_FAILURE;

    cycles   = wm_read(REG_CYCLES);
    windone  = wm_read(REG_WINDONE);
    instl    = wm_read(REG_INSTALL);
    outstl   = wm_read(REG_OUTSTALL);
    outcount = wm_read(REG_OUTCOUNT);
    bad      = compare_results(&first_bad);

    xil_printf("windows done   : %lu (expected %d)\r\n", (unsigned long)windone, NWINDOWS);
    xil_printf("results        : %lu (expected %lu)\r\n",
               (unsigned long)outcount, (unsigned long)RESULT_WORDS);
    xil_printf("MISMATCHES     : %lu\r\n", (unsigned long)bad);
    if (bad != 0) {
        xil_printf("  first at word %lu: got %08lx want %08lx\r\n",
                   (unsigned long)first_bad,
                   (unsigned long)((const volatile u32 *)ADDR_RESULT)[first_bad],
                   (unsigned long)((const volatile u32 *)ADDR_GOLD)[first_bad]);
    }
    xil_printf("CYCLES         : %lu\r\n", (unsigned long)cycles);
    xil_printf("  per window   : %lu.%02lu\r\n",
               (unsigned long)(cycles / NWINDOWS),
               (unsigned long)((cycles % NWINDOWS) * 100 / NWINDOWS));
    xil_printf("IN_STALL       : %lu\r\n", (unsigned long)instl);
    xil_printf("OUT_STALL      : %lu\r\n", (unsigned long)outstl);
    xil_printf("wall clock     : %lu us (PS timer, includes DMA setup)\r\n",
               (unsigned long)(elapsed / (COUNTS_PER_SECOND / 1000000)));

    if (bad != 0) {
        xil_printf("RESULT: FAIL -- values are wrong; the cycle count is meaningless.\r\n");
    } else if (instl != 0 || outstl != 0) {
        xil_printf("RESULT: VALUES OK, MEASUREMENT DMA BOUND -- the core waited %lu cycles for\r\n",
                   (unsigned long)(instl + outstl));
        xil_printf("        the memory path. CYCLES is not comparable with RESULTS_KO.md.\r\n");
    } else {
        xil_printf("RESULT: PASS -- core bound. CYCLES is comparable with total_cycles in\r\n");
        xil_printf("        verification/included_run/summary.json for the same configuration.\r\n");
    }
    return (bad == 0) ? XST_SUCCESS : XST_FAILURE;
}
