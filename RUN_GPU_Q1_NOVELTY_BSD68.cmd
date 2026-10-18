@echo off
rem Q1 novelty JOINT vs MARGINAL objective: GPU/CPU ONLY, no FPGA/JTAG.
rem USAGE:
rem   RUN_GPU_Q1_NOVELTY_BSD68.cmd smoke
rem   RUN_GPU_Q1_NOVELTY_BSD68.cmd full
rem   RUN_GPU_Q1_NOVELTY_BSD68.cmd full new   (force fresh run)
rem Reuses validated COMPLETE existing runs, otherwise chooses unused _02/_03 dir.
rem NEVER deletes or overwrites existing experiment output directories.
setlocal
pushd "%~dp0"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=smoke"
set "NEW_ARG="
if /I "%~2"=="new" set "NEW_ARG=--new"
if /I not "%MODE%"=="smoke" if /I not "%MODE%"=="full" (
    echo Usage: RUN_GPU_Q1_NOVELTY_BSD68.cmd smoke^|full [new]
    popd
    exit /b 2
)
python -u scripts\q1_novelty_bsd68_launcher.py "%MODE%" %NEW_ARG%
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo FAILED: see launcher details above. Previous runs are preserved.
)
popd
exit /b %RESULT%
