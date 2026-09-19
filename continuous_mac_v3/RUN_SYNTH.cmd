@echo off
setlocal
pushd "%~dp0"
where vivado >nul 2>nul
if errorlevel 1 goto missing
rem Optional: set CNN_P / CNN_DEPTH / CNN_T / CNN_CLOCK_NS / CNN_PART / CNN_CORES before running.
call vivado -mode batch -source scripts\synth_vivado.tcl
if errorlevel 1 goto failed
echo.
echo Read every core's routed_utilization.rpt and routed_timing.rpt.
echo Script completion does not guarantee timing closure. No bitstream was made.
pause
popd
exit /b 0
:missing
echo Vivado is not on PATH. Run your Vivado settings64.bat first.
:failed
echo STOPPED. Inspect the Vivado log.
pause
popd
exit /b 1
