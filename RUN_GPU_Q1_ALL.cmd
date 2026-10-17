@echo off
rem Deadline comprehensive GPU experiment matrix; RTX 4060 Ti recommended.
rem Safe: NO Vivado, no FPGA/JTAG, no model retraining, no overwrite of original weights.
rem RESUMABLE: if interrupted, rerun this exact CMD using the same options.
rem Stage 1 = multi-method optimization and full BSD68 3-sigma x 3-seed test.
rem Stage 2 = 64-ch QAT transfer, full BSD68 3-sigma x 2-seed test.
rem Stage 3 = maxout QAT transfer, full BSD68 3-sigma x 2-seed test.
rem Stage 4 = original/reordered output equality on Set12+BSD68, 3 sigma x 3 seed.
rem Stage 5 = factual research report based only on files generated locally.
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
echo.
echo ===== PRECHECK: Python syntax and frozen pilot data =====
python -m py_compile scripts\q1_gpu_deadline_suite.py scripts\q1_gpu_architecture_sweep.py scripts\q1_gpu_bitexact_stress.py scripts\q1_gpu_final_report.py
if errorlevel 1 goto failed
if not exist build\q1_reviewer_bank\report.json (
  echo Missing earlier frozen permutation report:
  echo   build\q1_reviewer_bank\report.json
  echo Run RUN_GPU_Q1_REVIEW.cmd first, or restore its original report.json.
  goto failed
)
if not exist build\q1_reviewer_export\dn_d10_c32_us_fx_qat\manifest.json (
  echo Missing reordered exported QAT model.
  echo Run RUN_GPU_Q1_REVIEW.cmd, or unzip the GitHub reordered QAT model into build\q1_reviewer_export.
  goto failed
)
echo.
echo ===== 1/5: 7 strategies + 20 random controls on BSD68, sigma 15/25/50, seed 0/1/2 =====
python -u scripts\q1_gpu_deadline_suite.py --model dn_d10_c32_us_fx_qat --dataset BSD68 --sigmas 15,25,50 --seeds 0,1,2 --calib-seeds 0,1 --calib-images 01.png,02.png,03.png --greedy-steps 400 --anneal-steps 1000 --restarts 4 --random-count 20 --device auto --out build\q1_gpu_deadline_full
if errorlevel 1 goto failed
echo.
echo ===== 2/5: other CNN architecture: 64-channel ReLU QAT =====
python -u scripts\q1_gpu_architecture_sweep.py --model dn_d10_c64_us_es_qat --sigmas 15,25,50 --seeds 0,1 --device auto --out build\q1_gpu_architectures
if errorlevel 1 goto failed
echo.
echo ===== 3/5: other CNN architecture: 32-channel maxout QAT =====
python -u scripts\q1_gpu_architecture_sweep.py --model dn_d10_c32_us_mo_fx_qat --sigmas 15,25,50 --seeds 0,1 --device auto --out build\q1_gpu_architectures
if errorlevel 1 goto failed
echo.
echo ===== 4/5: entire output equality stress over 80 images and 9 noise conditions =====
python -u scripts\q1_gpu_bitexact_stress.py --sets BSD68,Set12 --sigmas 15,25,50 --seeds 0,1,2 --device auto --out build\q1_gpu_bitexact_stress
if errorlevel 1 goto failed
echo.
echo ===== 5/5: evidence-only research summary =====
python scripts\q1_gpu_final_report.py
if errorlevel 1 goto failed
echo.
echo COMPLETED: no physical FPGA was programmed.
echo Share all these files:
echo   build\q1_gpu_deadline_full\summary.json
echo   build\q1_gpu_deadline_full\per_condition.csv
echo   build\q1_gpu_deadline_full\per_image_methods.csv
echo   build\q1_gpu_architectures\dn_d10_c64_us_es_qat\summary.json
echo   build\q1_gpu_architectures\dn_d10_c32_us_mo_fx_qat\summary.json
echo   build\q1_gpu_bitexact_stress\summary.json
echo   build\q1_gpu_deadline_final\EVIDENCE_REPORT_KO.md
popd
exit /b 0
:failed
echo.
echo FAILED OR STOPPED. Completed image rows are retained and NOT overwritten.
echo Please copy the LAST error output; rerunning this exact command resumes previous work.
python scripts\q1_gpu_final_report.py
popd
exit /b 1
