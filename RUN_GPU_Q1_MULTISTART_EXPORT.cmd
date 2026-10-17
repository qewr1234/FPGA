@echo off
rem FINAL multi-start QAT export from EXISTING completed GPU experiment, WITHOUT optimization.
rem 1. Strict completed-method report availability guard
rem 2. Real INT8 original-to-reordered QAT export (Set12 01 & 05 CPU oracle)
rem 3. Exact output equality on BSD68+Set12, sigma 15/25/50, seed 0/1/2
rem 4. SHA256-provenance verified local model ZIP package
rem No Vivado / FPGA / board programming. Original denoise/export weights never overwritten.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

echo.
echo [0/4] Checking existing selected Multi-start calibration and scripts...
python -m py_compile scripts\q1_reviewer_export.py scripts\q1_gpu_bitexact_stress.py scripts\q1_multistart_finalize.py
if errorlevel 1 goto failed
if not exist build\q1_gpu_deadline_full\export_multistart_greedy.json (
  echo ERROR: missing frozen multistart map build\q1_gpu_deadline_full\export_multistart_greedy.json
  goto failed
)
if not exist build\q1_gpu_deadline_full\method_config.json (
  echo ERROR: missing calibration map build\q1_gpu_deadline_full\method_config.json
  goto failed
)
if not exist build\q1_gpu_deadline_full\summary.json (
  echo ERROR: missing full GPU sweep summary
  goto failed
)

echo.
echo [1/4] Export real INT8 network with exactly learned Multi-start grouping...
python -u scripts\q1_reviewer_export.py --model dn_d10_c32_us_fx_qat --report build\q1_gpu_deadline_full\export_multistart_greedy.json --images 01.png,05.png --set Set12 --out build\q1_multistart_export
if errorlevel 1 goto failed

echo.
echo [2/4] Check full images across 80 test images x 3 sigmas x 3 noise seeds...
python -u scripts\q1_gpu_bitexact_stress.py --original denoise\export\dn_d10_c32_us_fx_qat --candidate build\q1_multistart_export\dn_d10_c32_us_fx_qat --sets BSD68,Set12 --sigmas 15,25,50 --seeds 0,1,2 --device auto --out build\q1_gpu_multistart_bitexact_stress
if errorlevel 1 goto failed

echo.
echo [3/4] Verify calibration map, model hashes, exact 720-condition result and ZIP integrity...
python -u scripts\q1_multistart_finalize.py --candidate build\q1_multistart_export\dn_d10_c32_us_fx_qat --stress build\q1_gpu_multistart_bitexact_stress\summary.json --out build\q1_multistart_verified_export_20261018.zip
if errorlevel 1 goto failed

echo.
echo [4/4] COMPLETED, no model retraining or physical FPGA.
echo Results to share:
echo   build\q1_gpu_deadline_full\export_multistart_greedy.json
echo   build\q1_gpu_multistart_bitexact_stress\summary.json
echo   build\q1_multistart_verified_export_20261018.zip
echo Existing frozen model and original model have NOT been overwritten.
popd
exit /b 0

:failed
echo.
echo ABORTED. Original QAT model not overwritten.
echo Share the error traceback and last stage. Re-running resumes the 720-case stress test.
popd
exit /b 1
