@echo off
rem GPU PC; validate frozen reordered int8 model for ALL BSD68 images.
rem No Vivado, bitstream, calibration, training or model modification.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_reviewer_bitexact_holdout.py
if errorlevel 1 goto failed
python scripts\q1_reviewer_bitexact_holdout.py --model dn_d10_c32_us_fx_qat --set BSD68 --device auto --out build\q1_reviewer_bitexact_holdout
if errorlevel 1 goto failed
echo.
echo Share: build\q1_reviewer_bitexact_holdout\report.json
echo Share: build\q1_reviewer_bitexact_holdout\per_image.csv
popd
exit /b 0
:failed
echo FAILED. Please copy the error output.
popd
exit /b 1
