@echo off
rem Research hypothesis screen. This PC needs PyTorch, NumPy and Set12 ONLY.
rem Does NOT synthesize RTL, install Vivado or flash a FPGA.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
echo [1/3] Python syntax check...
python -m py_compile scripts\q1_reviewer_bank.py scripts\q1_reviewer_export.py
if errorlevel 1 goto failed
echo [2/3] Held-out W=4 bank scheduling screen (calibration 01.png; evaluation 05.png)...
python scripts\q1_reviewer_bank.py --model dn_d10_c32_us_fx_qat --set Set12 --calib 01.png --eval 05.png --sample 2048 --steps 400 --device auto --out build\q1_reviewer_bank
if errorlevel 1 goto failed
echo [3/3] Re-export integer weights and verify full-image outputs unchanged...
python scripts\q1_reviewer_export.py --model dn_d10_c32_us_fx_qat --report build\q1_reviewer_bank\report.json --images 01.png,05.png --set Set12 --out build\q1_reviewer_export
if errorlevel 1 goto failed
echo.
echo PASS: share these with ChatGPT:
echo   build\q1_reviewer_bank\report.json
echo   build\q1_reviewer_export\dn_d10_c32_us_fx_qat\bitexact_report.json
echo No claims about actual FPGA timing are warranted at this stage.
popd
exit /b 0
:failed
echo.
echo FAILURE. Copy ALL error output to ChatGPT.
echo No existing model weights or FPGA RTL were modified.
popd
exit /b 1
