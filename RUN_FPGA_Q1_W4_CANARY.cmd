@echo off
rem Controlled physical ORIGINAL-ONLY canary with previously working W4 build.
rem This script WILL program the FPGA ONLY AFTER explicit human confirmation.
rem Usage: RUN_FPGA_Q1_W4_CANARY.cmd "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" canary_01
setlocal
pushd "%~dp0"
if "%~1"=="" goto usage
set "XSDB=%~1"
set "ID=%~2"
if "%ID%"=="" set "ID=canary_01"
set "BUILD=%CD%\build\zed_v4_p16_t4_w4_1792234898"
set "AUDIT=%CD%\build\q1_w4_provenance_audit\audit_01\audit.json"
set "BIT_SHA=11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6"
if not exist "%AUDIT%" (
  echo ERROR: missing previous provenance audit: %AUDIT%
  goto failed
)
if not exist "%XSDB%" (
  echo ERROR: XSDB path not found: %XSDB%
  goto failed
)
echo.
echo Step 1: OFFLINE checks. No FPGA access.
python -u scripts\q1_existing_w4_canary.py --audit "%AUDIT%" --build "%BUILD%" --expected-sha256 "%BIT_SHA%" --xsdb "%XSDB%" --run-id "%ID%"
if errorlevel 1 goto failed
echo.
echo IMPORTANT HARDWARE NOTICE:
echo Existing W4 project was generated with ZC702 PS preset.
echo Historical W4 execution passed, BUT past report does not have a .bit SHA.
echo Only proceed if this is the SAME physical board that safely ran original W4 before,
echo and you have checked the PSU, DDR/PS setup, and JTAG connection.
echo NOT for use on an unverified/new Smart ZYNQ SL board.
echo.
set "ACK="
set /p "ACK=Type SAME_PHYSICAL_BOARD_PREVIOUSLY_RAN_W4 only if confirmed: "
if not "%ACK%"=="SAME_PHYSICAL_BOARD_PREVIOUSLY_RAN_W4" goto cancelled
python -u scripts\q1_existing_w4_canary.py --audit "%AUDIT%" --build "%BUILD%" --expected-sha256 "%BIT_SHA%" --xsdb "%XSDB%" --run-id "%ID%" --execute --board-acknowledged "%ACK%"
if errorlevel 1 goto failed
echo.
echo SUCCESS. Review and upload:
echo %CD%\build\q1_existing_w4_canary\%ID%\canary.json
popd
exit /b 0
:cancelled
echo CANCELLED. No FPGA run started.
popd
exit /b 1
:failed
echo STOPPED. Check details. Existing result folders not overwritten.
popd
exit /b 1
:usage
echo RUN_FPGA_Q1_W4_CANARY.cmd "EXACT_XSDB_BAT_PATH" canary_01
popd
exit /b 1
