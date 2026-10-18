@echo off
rem CAUTION: can program real hardware. Never assumes ZedBoard PS preset is Smart ZYNQ SL compatible.
rem Usage: RUN_FPGA_Q1_BANK_AB.cmd "C:\Xilinx\Vivado\2026.1\bin\xsdb.bat" "C:\fpga\FPGA\build\SMART_ZYNQ_SL_APPROVED_W4" trial_01 1
rem Must manually check vendor DDR/MIO/PS settings and bitstream BEFORE authorizing.
setlocal
pushd "%~dp0"
if "%~1"=="" goto usage
if "%~2"=="" goto usage
set "RUN_ID=%~3"
if "%RUN_ID%"=="" set "RUN_ID=trial_01"
set "REPEAT=%~4"
if "%REPEAT%"=="" set "REPEAT=1"
echo.
echo WARNING: This command will physically program the FPGA and use PS DDR.
echo Compatible XC7Z020 PART NUMBER does NOT prove Smart ZYNQ SL PS7 DDR/MIO compatibility.
echo Do not confirm for an old ZedBoard build or any unvalidated bitstream.
echo.
set "APPROVAL="
set /p "APPROVAL=Type SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED only after hardware review: "
if not "%APPROVAL%"=="SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED" (
  echo CANCELLED. FPGA was not programmed.
  popd
  exit /b 1
)
python scripts\q1_fpga_bank_ab.py --execute --board-verified "%APPROVAL%" --xsdb "%~1" --build "%~2" --run-id "%RUN_ID%" --repeat "%REPEAT%"
if errorlevel 1 (
  echo ERROR: A/B aborted; see exception. Previous run data was never intentionally overwritten.
  popd
  exit /b 1
)
popd
exit /b 0
:usage
echo.
echo First run: RUN_FPGA_Q1_BANK_PREFLIGHT.cmd
echo To PROGRAM verified Smart ZYNQ SL hardware:
echo RUN_FPGA_Q1_BANK_AB.cmd "PATH_TO_XSDB" "PATH_TO_VERIFIED_SMART_ZYNQ_SL_W4_BUILD" trial_01 1
echo Requires explicit approval; does not auto-select legacy ZedBoard builds.
popd
exit /b 1
