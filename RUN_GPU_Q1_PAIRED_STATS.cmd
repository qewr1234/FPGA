@echo off
rem Run paired image-cluster GPU study statistics on already completed CSV.
rem No CNN inference, no GPU compute, no Vivado, no FPGA access.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_gpu_pairwise_stats.py
if errorlevel 1 goto failed
python -u scripts\q1_gpu_pairwise_stats.py --input build\q1_gpu_deadline_full\per_image_methods.csv --out build\q1_gpu_deadline_final --bootstrap 4000
if errorlevel 1 goto failed
echo.
echo PASS. Share:
echo   build\q1_gpu_deadline_final\PAIRED_STATS.md
echo   build\q1_gpu_deadline_final\paired_tests.json
echo   build\q1_gpu_deadline_final\paired_tests.csv
echo   build\q1_gpu_deadline_final\method_comparison.png
popd
exit /b 0
:failed
echo FAIL. Send the error log and the original CSV.
popd
exit /b 1
