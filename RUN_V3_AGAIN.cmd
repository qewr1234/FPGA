@echo off
rem The four Channel points measured on 2026-09-22 carried RUNTIME_GEOM, which
rem Bank does not have: +140 LUT at P=2, in one of the two cores being compared.
rem RUNTIME_GEOM now defaults to 0, so re-running these puts every point back on
rem the design the paper describes. About 40 minutes. Nothing else needs redoing:
rem Bank was never changed, and the bitstreams measure cycles, not area.
pushd "%~dp0"
call "%~dp0scripts\find_vivado.cmd"
if errorlevel 1 (
  echo Vivado not found. set XILINX_VIVADO=C:\Vivado\2026.1\Vivado and re-run.
  pause
  popd
  exit /b 1
)
set CNN_MAX_DSP=0
set CNN_DEPTH=2
set CNN_CLOCK_NS=10.0
set CNN_CORES=overlapped_window_mac
set CNN_T=1
for %%P in (2 4 16 64) do call :job %%P
echo.
echo Done. Now:  python scripts\collect_utilization.py --dsp-free
echo Every Channel row should read RUNTIME_GEOM off; P=2 back near 992 LUT.
pause
popd
exit /b 0

:job
set "CNN_P=%~1"
if not "%CNN_P%"=="%~1" (
  echo     ABORT: CNN_P reads "%CNN_P%" but should be "%~1"
  exit /b 0
)
if not exist logs mkdir logs
echo.
echo ---- ooc Channel P=%CNN_P%
>> logs\progress.txt echo %date% %time%  START ooc Channel P=%CNN_P%
call vivado -mode batch -source scripts\synth_vivado.tcl -log "logs\ooc_ch_P%CNN_P%.log" -nojournal
if errorlevel 1 (echo     FAILED) else (echo     ok)
exit /b 0
