@echo off
rem Publishable equal-objective-evaluation benchmarking. GPU only.
rem 5 optimizer seeds x 3 budgets, 3 methods; clean images BSD68 held out.
rem Analysis does not modify the existing 10.709% frozen/multistart model.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
python -m py_compile scripts\q1_fair_budget.py
if errorlevel 1 goto failed
python scripts\q1_fair_budget.py --selftest
if errorlevel 1 goto failed
if not exist build\q1_reviewer_bank\report.json (
  echo ERROR: missing frozen model training report: build\q1_reviewer_bank\report.json
  echo Use your original saved report from RUN_GPU_Q1_REVIEW.cmd
  goto failed
)
echo.
echo EQUAL BUDGET STUDY: 400, 800, 2000 objective evaluations per method.
echo Five optimizer seeds: 42,101,202,303,404.
echo Calibration: Set12 01/02/03 with seed0/1; all competitors identical.
echo Evaluation: 68 BSD68 x 3 sigma x 3 AWGN seed, reused across optimizer seeds.
echo GPU hardware only. NO FPGA/JTAG/Vivado.
echo.
python -u scripts\q1_fair_budget.py --budgets 400,800,2000 --optimizer-seeds 42,101,202,303,404 --restarts 5 --calib-windows 1024 --device auto --out build\q1_gpu_fair_budget
if errorlevel 1 goto failed
echo.
echo SUCCESS. Share:
echo   build\q1_gpu_fair_budget\summary.json
echo   build\q1_gpu_fair_budget\method_summary.csv
echo   build\q1_gpu_fair_budget\fair_paired.csv
echo   build\q1_gpu_fair_budget\search_effort.csv
popd
exit /b 0
:failed
echo.
echo STOPPED. Completed results are preserved; use same CMD to resume.
popd
exit /b 1
