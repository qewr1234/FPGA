@echo off
rem GPU-PC (no Vivado). Evaluate FROZEN bank permutation on all BSD68 images.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_reviewer_holdout.py
if errorlevel 1 goto failed
python scripts\q1_reviewer_holdout.py --model dn_d10_c32_us_fx_qat --report build\q1_reviewer_bank\report.json --set BSD68 --device auto --out build\q1_reviewer_holdout
if errorlevel 1 goto failed
echo.
echo SHARE: build\q1_reviewer_holdout\report.json
echo SHARE: build\q1_reviewer_holdout\per_image.csv
popd
exit /b 0
:failed
echo FAILED. Copy the error to ChatGPT. Existing model and RTL not modified.
popd
exit /b 1
