@echo off
rem Optional rapid diagnostics / proof that all dependencies and code paths work.
rem Does NOT replace the complete RUN_GPU_Q1_ALL.cmd research suite.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
python -m py_compile scripts\q1_gpu_deadline_suite.py scripts\q1_gpu_architecture_sweep.py scripts\q1_gpu_bitexact_stress.py scripts\q1_gpu_final_report.py
if errorlevel 1 goto failed
if not exist build\q1_reviewer_bank\report.json goto needoriginal
python -u scripts\q1_gpu_deadline_suite.py --sigmas 25 --seeds 0 --calib-seeds 0 --max-images 2 --greedy-steps 40 --anneal-steps 60 --restarts 1 --random-count 3 --device auto --out build\q1_gpu_smoke_full
if errorlevel 1 goto failed
python -u scripts\q1_gpu_architecture_sweep.py --model dn_d10_c64_us_es_qat --sigmas 25 --seeds 0 --max-images 1 --greedy-steps 40 --anneal-steps 60 --restarts 1 --device auto --out build\q1_gpu_smoke_arch
if errorlevel 1 goto failed
python -u scripts\q1_gpu_architecture_sweep.py --model dn_d10_c32_us_mo_fx_qat --sigmas 25 --seeds 0 --max-images 1 --greedy-steps 40 --anneal-steps 60 --restarts 1 --device auto --out build\q1_gpu_smoke_arch
if errorlevel 1 goto failed
python -u scripts\q1_gpu_bitexact_stress.py --sets Set12 --sigmas 25 --seeds 0 --max-images 1 --device auto --out build\q1_gpu_smoke_exact
if errorlevel 1 goto failed
echo ALL SMOKE TESTS PASS. Now run RUN_GPU_Q1_ALL.cmd for complete study.
popd
exit /b 0
:needoriginal
echo Run RUN_GPU_Q1_REVIEW.cmd first: frozen report missing.
:failed
echo FAILED. Please send full error output, do not overwrite original models.
popd
exit /b 1
