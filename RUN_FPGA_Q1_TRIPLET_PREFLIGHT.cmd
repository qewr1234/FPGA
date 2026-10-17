@echo off
rem Preflight only: original, frozen and multistart integrity, no FPGA connection.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_fpga_triplet.py
if errorlevel 1 goto failed
python scripts\q1_fpga_triplet.py
if errorlevel 1 goto failed
echo PASS: FPGA JTAG/bitstream untouched; all three models ready.
popd
exit /b 0
:failed
echo FAILED: see traceback, do NOT program board.
popd
exit /b 1
