@echo off
rem Triple-run physically programs connected Smart ZYNQ SL FPGA AFTER MANUAL approval.
rem Usage: RUN_FPGA_Q1_TRIPLET.cmd "C:\path\to\xsdb.bat" "C:\path\to\VERIFIED_SMART_ZYNQ_SL_W4_BUILD" trial_01
rem The third argument is a fresh run ID (never reuse old output).
setlocal
pushd "%~dp0"
if "%~1"=="" goto usage
if "%~2"=="" goto usage
set "RUN_ID=%~3"
if "%RUN_ID%"=="" set "RUN_ID=trial_01"
echo.
echo WARNING: actual FPGA programming will run 3 repetitions x 3 models.
echo You must verify the bitstream PS DDR/MIO, clocks and pinout against SMART ZYNQ SL.
echo Matching XC7Z020 silicon is NOT proof of board-specific PS config compatibility.
echo NEVER approve a ZedBoard bitstream for this board without a full board-specific review.
echo.
set "APPROVAL="
set /p "APPROVAL=Type SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED only if APPROVED: "
if not "%APPROVAL%"=="SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED" goto cancelled
python -u scripts\q1_fpga_triplet.py --execute --board-verified "%APPROVAL%" --xsdb "%~1" --build "%~2" --run-id "%RUN_ID%" --repeats 3 --image 05.png --fclk 50
if errorlevel 1 goto failed
echo.
echo PHYSICAL MEASUREMENTS:
echo   build\q1_bank_fpga_triplet\%RUN_ID%\triplet_summary.json
echo   build\q1_bank_fpga_triplet\%RUN_ID%\triplet_summary.md
popd
exit /b 0
:cancelled
echo CANCELLED: no FPGA programming attempted.
popd
exit /b 1
:usage
echo 1. RUN_FPGA_Q1_TRIPLET_PREFLIGHT.cmd
echo 2. RUN_FPGA_Q1_TRIPLET.cmd "PATH_TO_XSDB" "PATH_TO_VERIFIED_SMART_ZYNQ_SL_W4_BUILD" trial_01
echo Be certain of all PS DDR/MIO settings; use ONLY board-verified build.
popd
exit /b 1
:failed
echo FAILED; inspect traceback. Existing outputs are not intentionally overwritten.
popd
exit /b 1
