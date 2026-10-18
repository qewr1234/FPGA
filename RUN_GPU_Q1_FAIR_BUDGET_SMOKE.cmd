@echo off
rem Fast smoke test on two BSD68 images, small budget, separate output folder.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_fair_budget.py
if errorlevel 1 goto failed
python scripts\q1_fair_budget.py --selftest
if errorlevel 1 goto failed
python -u scripts\q1_fair_budget.py --budgets 50,100 --optimizer-seeds 42 --restarts 5 --max-images 2 --device auto --out build\q1_gpu_fair_budget_smoke
if errorlevel 1 goto failed
echo PASS. Now run RUN_GPU_Q1_FAIR_BUDGET.cmd.
popd
exit /b 0
:failed
echo FAILED; no FPGA or original model writes performed.
popd
exit /b 1
