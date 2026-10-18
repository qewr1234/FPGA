@echo off
rem Q1 consolidated paper experiments. No previous outputs are overwritten.
rem Read research/q1_codesign/Q1_ALL_EXPERIMENTS_README_KO.md before physical use.
rem PLAN (no board/GPU): RUN_Q1_ALL_EXPERIMENTS.cmd plan
rem GPU only:           RUN_Q1_ALL_EXPERIMENTS.cmd gpu
rem ALL physical images plus GPU: RUN_Q1_ALL_EXPERIMENTS.cmd all "C:\Vivado\2026.1\Vivado\bin\xsdb.bat"
rem GPU + 3 physical images: RUN_Q1_ALL_EXPERIMENTS.cmd all "C:\Vivado\2026.1\Vivado\bin\xsdb.bat" 04.png,06.png,08.png
rem FPGA only:          RUN_Q1_ALL_EXPERIMENTS.cmd fpga "C:\Vivado\2026.1\Vivado\bin\xsdb.bat"
rem NOTE: 'all' / 'fpga' requires SAME tested board with W4 canary and prompt;
rem it really reprograms physical FPGA and can take hours.
setlocal
pushd "%~dp0"
set "STAGE=%~1"
if "%STAGE%"=="" set "STAGE=plan"
if /I "%STAGE%"=="plan" goto offline
if /I "%STAGE%"=="gpu" goto offline
if /I "%STAGE%"=="all" goto physical
if /I "%STAGE%"=="fpga" goto physical
goto usage
:offline
python -u scripts\q1_all_experiments.py --stage "%STAGE%"
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%
:physical
if "%~2"=="" goto usage
if "%~3"=="" (
  python -u scripts\q1_all_experiments.py --stage "%STAGE%" --xsdb "%~2"
) else (
  python -u scripts\q1_all_experiments.py --stage "%STAGE%" --xsdb "%~2" --images "%~3"
)
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%
:usage
echo Usage: RUN_Q1_ALL_EXPERIMENTS.cmd plan^|gpu^|all^|fpga ["XSDB_PATH"] [04.png,06.png,08.png]
popd
exit /b 2
