@echo off
rem Fills in the Channel points between 2 and 64. The re-run has 2, 16 and 64,
rem and the LUT cost per multiplier is clearly not constant over that range --
rem 98 per multiplier from 2 to 16, 134 from 16 to 64 -- so the curve between
rem them needs sampling rather than assuming. About 30 minutes. P=4 also failed
rem to produce a report on its first attempt, so it is included here.
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
for %%P in (4 8 32) do call :job %%P
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
