@echo off
rem Out-of-context synthesis / place / route of the four cores on the same part
rem and clock, for the Fmax and resource comparison. No bitstream is made here;
rem RUN_BUILD_ZED.cmd builds the board design.
rem
rem Optional before running:
rem   set CNN_P=8  /  CNN_DEPTH=2  /  CNN_T=4  /  CNN_CLOCK_NS=10.0
rem   set CNN_PART=xc7z020clg484-1
rem   set CNN_CORES=overlapped_window_mac banked_window_mac
pushd "%~dp0"

call "%~dp0scripts\find_vivado.cmd"
if errorlevel 1 goto missing

call vivado -mode batch -source scripts\synth_vivado.tcl
if errorlevel 1 goto failed

echo.
echo Read every core's routed_utilization.rpt and routed_timing.rpt in build\ooc_*.
echo Script completion does not guarantee timing closure. No bitstream was made.
pause
popd
exit /b 0

:missing
echo.
echo Vivado was not found.
echo.
echo Option 1 - use the Vivado Tcl Shell, which already has PATH set:
echo     Start menu -^> Xilinx Design Tools -^> Vivado 20xx.x Tcl Shell
echo   then in that shell:
echo     cd {%~dp0}
echo     source scripts/synth_vivado.tcl
echo.
echo Option 2 - tell this script where Vivado is, then re-run it:
echo     set XILINX_VIVADO=C:\Xilinx\Vivado\2023.2
echo     RUN_SYNTH.cmd
echo.
echo Option 3 - source the settings script yourself, then re-run this:
echo     call "C:\Xilinx\Vivado\2023.2\settings64.bat"
echo.
echo If no such directory exists, Vivado is not installed on this machine.
pause
popd
exit /b 1

:failed
echo.
echo STOPPED. Inspect the Vivado log (vivado.log in this directory).
pause
popd
exit /b 1
