@echo off
rem GPU PC only. This stage is an analytical CPU study and bit-exact oracle test.
rem No Vivado, no FPGA, no training, no downloaded dependencies needed.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
echo [1/2] Checking tiled conv2+conv3 against exact INT8 oracle...
python scripts\q1_fusion_selftest.py
if errorlevel 1 goto failed
echo.
echo [2/2] Screening tile sides / BRAM capacity / DDR stream proxies...
python scripts\q1_fusion_cost.py --image-size 256x256 --tiles 16,24,32,40,48,56,64,80,96 --buffer-safety-factor 1.25 --reserve-bram36 16 --buffer-sets 1 --out build\q1_fusion_screen
if errorlevel 1 goto failed
echo.
echo SUCCESS. Share:
echo   build\q1_fusion_screen\candidates.csv
echo   build\q1_fusion_screen\summary.json
popd
exit /b 0
:failed
echo FAILED. Copy the error output to ChatGPT. No FPGA files were changed.
popd
exit /b 1
