@echo off
rem Real Original/Frozen/Multi-start physical W4 comparisons on PREVIOUSLY WORKING board.
rem REQUIRE successful Original-only canary proving THIS SAME local .bit SHA.
rem Usage: RUN_FPGA_Q1_TRIPLET_EXISTING_W4.cmd "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" canary_01 trial_01 [Set12_image.png]
rem WARNING: THIS SCRIPT PROGRAMS THE FPGA after user approval.
setlocal
pushd "%~dp0"
if "%~1"=="" goto usage
set "XSDB=%~1"
set "CANARY_ID=%~2"
if "%CANARY_ID%"=="" set "CANARY_ID=canary_01"
set "TRIAL_ID=%~3"
if "%TRIAL_ID%"=="" set "TRIAL_ID=trial_01"
set "IMAGE=%~4"
if "%IMAGE%"=="" set "IMAGE=05.png"
set "CANARY=%CD%\build\q1_existing_w4_canary\%CANARY_ID%\canary.json"
set "BUILD=%CD%\build\zed_v4_p16_t4_w4_1792234898"
if not exist "%CANARY%" (
  echo ERROR: Missing passed physical W4 canary: %CANARY%
  goto failed
)
if not exist "%XSDB%" (
  echo ERROR: XSDB not found: %XSDB%
  goto failed
)
echo.
echo DANGER: THIS WILL PROGRAM THE CONNECTED FPGA AND RUN 9 BOARD MEASUREMENTS.
echo 3 repetitions x Original, Frozen and Multi-start.
echo Set12 image: %IMAGE%
echo Only if this is the EXACT SAME previously working physical board.
echo Physical canary will be checked with .bit SHA256 before programming.
echo Historical build BoardPart is ZC702; do NOT use on an unverified board.
echo.
set "APPROVAL="
echo The completed Original-only physical canary confirms operation on this tested board.
echo It does NOT certify a manufacturer-specific PS DDR/MIO preset.
echo Only continue if the same FPGA board and cabling remain in use.
set /p "APPROVAL=Type SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED only if confirmed: "
if not "%APPROVAL%"=="SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED" goto cancelled
python -u scripts\q1_fpga_triplet.py --execute --board-verified "%APPROVAL%" --existing-w4-canary "%CANARY%" --xsdb "%XSDB%" --build "%BUILD%" --run-id "%TRIAL_ID%" --repeats 3 --image "%IMAGE%" --fclk 50
if errorlevel 1 goto failed
echo.
echo Results:
echo %CD%\build\q1_bank_fpga_triplet\%TRIAL_ID%\triplet_summary.json
echo %CD%\build\q1_bank_fpga_triplet\%TRIAL_ID%\triplet_summary.md
popd
exit /b 0
:cancelled
echo CANCELLED: no new board programming attempted.
popd
exit /b 1
:failed
echo FAILED: inspect logs; do not claim FPGA speedup unless all board runs pass.
popd
exit /b 1
:usage
echo RUN_FPGA_Q1_TRIPLET_EXISTING_W4.cmd "EXACT_XSDB_PATH" canary_01 trial_01 [Set12_image.png]
popd
exit /b 1
