@echo off
rem Build the Zedboard design (Zynq PS + AXI DMA + one core) through to a bitstream.
rem
rem   RUN_BUILD_ZED.cmd [IMPL] [P] [T] [CLOCK_MHZ]
rem
rem   IMPL       2 = overlapped_window_mac (v3), 3 = banked_window_mac (v4). Default 2.
rem   P          output-channel lanes. Default 8.
rem   T          tap banks, v4 only. Default 4.
rem   CLOCK_MHZ  fabric clock. Default 100.
rem
rem Examples:
rem   RUN_BUILD_ZED.cmd              v3, P=8, 100 MHz  (start here)
rem   RUN_BUILD_ZED.cmd 3 8 8 100    v4, P=8, T=8
rem   RUN_BUILD_ZED.cmd 2 64 1 100   v3, P=64  (the equal-multiplier pair with the above)
pushd "%~dp0"
rem Tcl wants forward slashes, so keep a slash-form of this directory for the messages.
set "WM_HERE=%~dp0"
set "WM_HERE=%WM_HERE:\=/%"

if "%~1"=="" (set CNN_IMPL=2) else (set CNN_IMPL=%~1)
if "%~2"=="" (set CNN_P=8)    else (set CNN_P=%~2)
if "%~3"=="" (set CNN_T=4)    else (set CNN_T=%~3)
if "%~4"=="" (set CNN_CLOCK_MHZ=100) else (set CNN_CLOCK_MHZ=%~4)
if not defined CNN_DEPTH set CNN_DEPTH=2

echo Building: IMPL=%CNN_IMPL% P=%CNN_P% DEPTH=%CNN_DEPTH% T=%CNN_T% clock=%CNN_CLOCK_MHZ% MHz
echo This runs synthesis and implementation and takes a while. Leave it alone.
echo.

call "%~dp0scripts\find_vivado.cmd"
if errorlevel 1 goto missing

call vivado -mode batch -source scripts\build_zedboard.tcl
if errorlevel 1 goto failed

echo.
echo Look for system_wrapper.bit and system_wrapper.xsa in build\zed_*.
echo Check the WNS the script printed: a negative WNS means the bitstream will
echo produce wrong values, not just slow ones. Lower the clock and rebuild.
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
echo     cd {%WM_HERE%}
echo     set ::env(CNN_IMPL) %CNN_IMPL%
echo     set ::env(CNN_P) %CNN_P%
echo     set ::env(CNN_T) %CNN_T%
echo     set ::env(CNN_CLOCK_MHZ) %CNN_CLOCK_MHZ%
echo     source scripts/build_zedboard.tcl
echo.
echo Option 2 - tell this script where Vivado is, then re-run it:
echo     set XILINX_VIVADO=C:\Xilinx\2026.1\Vivado    (or wherever settings64.bat lives)
echo     RUN_BUILD_ZED.cmd
echo.
echo If no such directory exists, Vivado is not installed on this machine.
pause
popd
exit /b 1

:failed
echo.
echo STOPPED. Inspect vivado.log in this directory, and the run logs under build\zed_*.
echo BOARD_KO.md lists what usually fails first (board files, interface inference).
pause
popd
exit /b 1
