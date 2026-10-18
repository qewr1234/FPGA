@echo off
rem Read-only CPU study: no FPGA or Vivado needed.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python scripts\q1_host_profile.py --model dn_d10_c32_us_fx_qat --height 256 --width 256 --repeats 5 --out build\q1_host_profile
set "RC=%errorlevel%"
if not "%RC%"=="0" echo Q1 host profiling FAILED.
echo.
echo Please share build\q1_host_profile\layers.csv and summary.json
popd
exit /b %RC%
