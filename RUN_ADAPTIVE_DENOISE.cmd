@echo off
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"

echo [1/4] Checking Python and PyTorch...
python -c "import torch, numpy, PIL; print('Torch:',torch.__version__); print('CUDA:',torch.cuda.is_available()); print('GPU:',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU fallback')"
if errorlevel 1 goto failed

echo [2/4] Checking crop equivalence (CPU smoke test)...
python research\adaptive_denoise\smoke_test.py
if errorlevel 1 goto failed

echo [3/4] Checking Set12 dataset and model...
if not exist "denoise\data\Set12\01.png" (
  echo Set12 missing. Downloading repository's pinned denoising datasets...
  python denoise\get_data.py
  if errorlevel 1 goto failed
)
if not exist "denoise\dn_d10_c32_us_mo_fx.pt" (
  echo ERROR: Missing denoise\dn_d10_c32_us_mo_fx.pt
  goto failed
)

echo [4/4] Running float CNN selective tile feasibility screen...
python research\adaptive_denoise\screen.py --set Set12 --sigma 25 --tile 128 --budgets 0,0.25,0.5,0.75,1 --out research\adaptive_denoise\runs\screen_v1
if errorlevel 1 goto failed

echo.
echo PASS. Result: research\adaptive_denoise\runs\screen_v1\summary.csv
popd
exit /b 0

:failed
echo.
echo FAILED. Please copy the console error. Existing model files are unchanged.
popd
exit /b 1
