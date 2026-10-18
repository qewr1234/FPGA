@echo off
rem Safe ZIP/model preflight for the frozen bank-reordered FPGA denoiser.
rem Never connects to or programs the FPGA.
setlocal
pushd "%~dp0"
python scripts\q1_fpga_bank_ab.py
if errorlevel 1 (
  echo.
  echo FAIL: preflight did not pass. No FPGA access was attempted.
  popd
  exit /b 1
)
echo.
echo PASS: original model untouched; frozen reordered model installed in build\q1_reviewer_export.
echo READY FOR MANUAL HARDWARE-COMPATIBILITY REVIEW; FPGA NOT PROGRAMMED.
popd
exit /b 0
