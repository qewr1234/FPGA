@echo off
rem Q1 novelty, JOINT vs MARGINAL objective; GPU/CPU ONLY, no FPGA/JTAG.
rem RUN_GPU_Q1_NOVELTY_BSD68.cmd smoke  = 2 BSD68 images, 25 sigma, noise seed 0
rem RUN_GPU_Q1_NOVELTY_BSD68.cmd full   = all BSD68 68 images x 3 sigma x 3 noise seeds
setlocal
pushd "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=smoke"
if /I "%MODE%"=="smoke" (
    set "OUT=build\q1_novelty_bsd68_smoke"
    python -u scripts\q1_novelty_bsd68_holdout.py --max-images 2 --sigma 25 --noise-seeds 0 --out "%OUT%"
) else if /I "%MODE%"=="full" (
    set "OUT=build\q1_novelty_bsd68_full"
    python -u scripts\q1_novelty_bsd68_holdout.py --out "%OUT%"
) else (
    echo Usage: RUN_GPU_Q1_NOVELTY_BSD68.cmd smoke^|full
    popd
    exit /b 2
)
if errorlevel 1 (
    echo FAILED. Existing experiment outputs were not intentionally overwritten.
    popd
    exit /b 1
)
echo.
echo Offline W4 core-CYCLE PROXY experiment complete. This is NOT physical FPGA.
echo Output: %CD%\%OUT%\summary.json
echo Output: %CD%\%OUT%\per_condition.csv
echo Output: %CD%\%OUT%\groups.json
popd
exit /b 0
