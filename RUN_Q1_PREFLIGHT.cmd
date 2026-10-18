@echo off
rem Q1 Stage 1 preflight: does not build or program any FPGA bitstream.
setlocal
pushd "%~dp0"
if not exist "build\q1_preflight" mkdir "build\q1_preflight"

echo Finding Vivado (required: 2026.1) ...
call scripts\find_vivado.cmd > "build\q1_preflight\vivado_lookup.log" 2>&1
if errorlevel 1 (
    echo Could not locate Vivado. See build\q1_preflight\vivado_lookup.log
)

python scripts\q1_preflight.py --output build\q1_preflight\report.json
set "RC=%errorlevel%"
echo.
echo Send build\q1_preflight\report.json to ChatGPT.
echo No bitstream was built or programmed.
popd
exit /b %RC%
