@echo off
rem Everything the results still need, in one pass. Roughly 3-4 hours unattended.
rem
rem Part 1 fills the gaps in the resource table. Only two DSP-free points exist
rem for v3, so its cost per multiplier is a line through two points rather than a
rem slope; P=2, 4, 16 and 64 make it a real fit, and v4 at P=16 T=4 is the other
rem half of the equal-multiplier pair.
rem
rem Part 2 builds the two bitstreams for that pair: v3 at P=64 against v4 at
rem P=16 T=4, both spending 64 multipliers. Until these run on the board, the
rem comparison at 64 multipliers is synthesis only.
rem
rem A job that fails does not stop the rest -- P=64 may not fit or close timing
rem on this part, and that outcome is itself a result worth having.
pushd "%~dp0"
set "WM_HERE=%~dp0"
set "WM_HERE=%WM_HERE:\=/%"
call "%~dp0scripts\find_vivado.cmd"
if errorlevel 1 goto missing
set "WM_FAILED="

echo.
echo ================ Part 1: out-of-context synthesis ================
set CNN_MAX_DSP=0
set CNN_DEPTH=2
set CNN_CLOCK_NS=10.0

set CNN_CORES=overlapped_window_mac
set CNN_T=1
for %%P in (2 4 16 64) do call :job "ooc v3 P=%%P" scripts\synth_vivado.tcl CNN_P=%%P

set CNN_CORES=banked_window_mac
set CNN_T=4
call :job "ooc v4 P=16 T=4" scripts\synth_vivado.tcl CNN_P=16

echo.
echo ================ Part 2: bitstreams for the 64-multiplier pair ================
set CNN_CLOCK_MHZ=100
set CNN_IMPL=2
set CNN_T=1
call :job "bitstream v3 P=64" scripts\build_zedboard.tcl CNN_P=64
set CNN_IMPL=3
set CNN_T=4
call :job "bitstream v4 P=16 T=4" scripts\build_zedboard.tcl CNN_P=16

echo.
echo ================ done ================
if defined WM_FAILED (
  echo These jobs failed: %WM_FAILED%
  echo Their logs are in logs\. A build that does not fit or does not close
  echo timing is a finding, not a mistake -- keep the log and say so.
) else (
  echo All jobs completed.
)
echo.
echo Next:
echo   python scripts\collect_utilization.py --dsp-free
echo     reads every build\ooc_* and prints the rows for paper\figures\data.py
echo   then, for each new bitstream, in xsdb:
echo     set ::env(WM_BUILD) C:/fpga/FPGA/build/zed_v3_p64_t1_XXXXXXXX
echo     source scripts/run_board_xsdb.tcl
echo   with build\board holding a matching export.
pause
popd
exit /b 0

:job
rem %1 label, %2 tcl script, %3 NAME=VALUE for this job
set "%~3"
if not exist logs mkdir logs
set "WM_LOG=logs\%~1.log"
set "WM_LOG=%WM_LOG: =_%"
echo.
echo ---- %~1  (log: %WM_LOG%)
call vivado -mode batch -source %2 -log "%WM_LOG%" -nojournal
if errorlevel 1 (
  echo     FAILED: %~1
  set "WM_FAILED=%WM_FAILED% [%~1]"
) else (
  echo     ok: %~1
)
exit /b 0

:missing
echo.
echo Vivado was not found. Open the Vivado Tcl Shell and run the jobs by hand,
echo or set XILINX_VIVADO to the Vivado directory and re-run this script.
pause
popd
exit /b 1
