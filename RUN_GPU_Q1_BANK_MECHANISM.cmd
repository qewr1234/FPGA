@echo off
rem Explain WHY W4 Sparse cycle estimates improve, layer-by-layer.
rem No original data, model weights, FPGA/JTAG/RTL are modified.
rem BSD68 full 68 x 3 noise sigma x 3 AWGN seed; resumable.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
python -m py_compile scripts\q1_bank_mechanism.py
if errorlevel 1 goto failed
python scripts\q1_bank_mechanism.py --selftest
if errorlevel 1 goto failed
if not exist build\q1_reviewer_bank\report.json (
  echo ERROR: missing calibration report build\q1_reviewer_bank\report.json
  goto failed
)
python -u scripts\q1_bank_mechanism.py --sigmas 15,25,50 --seeds 0,1,2 --device auto --out build\q1_gpu_bank_mechanism
if errorlevel 1 goto failed
echo.
echo PASS: layer x sigma bottleneck reports:
echo   build\q1_gpu_bank_mechanism\summary.json
echo   build\q1_gpu_bank_mechanism\sigma_layer_bottlenecks.csv
echo   build\q1_gpu_bank_mechanism\per_image_layer.csv
popd
exit /b 0
:failed
echo STOPPED; rerun this CMD to resume previously completed image groups.
popd
exit /b 1
