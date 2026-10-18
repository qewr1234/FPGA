@echo off
rem READ-ONLY audit of existing W4 real-board history vs current .bit SHA256.
rem No Vivado, XSDB, JTAG, PS DDR access, bitstream download or board programming.
rem Usage: RUN_FPGA_Q1_W4_PROVENANCE.cmd "C:\fpga\FPGA\build\YOUR_W4_BUILD" audit_01
setlocal
pushd "%~dp0"
if "%~1"=="" goto usage
set "RUN_ID=%~2"
if "%RUN_ID%"=="" set "RUN_ID=audit_01"
if not exist "%~1\system_wrapper.bit" (
  echo ERROR: W4 bitstream not found: %~1\system_wrapper.bit
  popd
  exit /b 1
)
python -u scripts\q1_w4_provenance_audit.py --build "%~1" --out "build\q1_w4_provenance_audit\%RUN_ID%"
if errorlevel 1 (
  echo ERROR: Provenance audit failed, or run-id already exists.
  popd
  exit /b 1
)
echo.
echo Result JSON: %CD%\build\q1_w4_provenance_audit\%RUN_ID%\audit.json
echo Result MD:   %CD%\build\q1_w4_provenance_audit\%RUN_ID%\audit.md
echo READ-ONLY: No FPGA/JTAG/XSDB access. No automatic board approval.
popd
exit /b 0
:usage
echo Usage: RUN_FPGA_Q1_W4_PROVENANCE.cmd "FULL_PATH_TO_EXISTING_W4_BUILD" audit_01
popd
exit /b 1
