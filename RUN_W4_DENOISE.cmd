@echo off
rem Run the paper's four denoisers on the four-wide (W=4) bitstream, Set12 05.png,
rem and copy each report next to the one-value-per-cycle runs in denoise\board_runs.
rem
rem   RUN_W4_DENOISE.cmd [xsdb]        default C:/Vivado/2026.1/Vivado/bin/xsdb.bat
rem
rem Needs a build\zed_v4_p16_t4_w4_* bitstream and uses the newest one. Build it with
rem   set CNN_K=1152
rem   set CNN_COUT=128
rem   set CNN_RUNTIME_GEOM=1
rem   RUN_BUILD_ZED.cmd 3 16 4 100 4
rem
rem The smallest network runs first, so a problem shows up in minutes, not an hour.
rem The PL clock is set to 50 MHz, the clock of every one-value-per-cycle board run.
setlocal
pushd "%~dp0"
set "XSDB=%~1"
if "%XSDB%"=="" set "XSDB=C:/Vivado/2026.1/Vivado/bin/xsdb.bat"
set "W4BUILD="
for /f "delims=" %%d in ('dir /b /ad /o:n build\zed_v4_p16_t4_w4_* 2^>nul') do (
    if exist "build\%%d\system_wrapper.bit" set "W4BUILD=build\%%d"
)
if "%W4BUILD%"=="" (
    echo No build\zed_v4_p16_t4_w4_*\system_wrapper.bit here. Build it first:
    echo   set CNN_K=1152
    echo   set CNN_COUT=128
    echo   set CNN_RUNTIME_GEOM=1
    echo   RUN_BUILD_ZED.cmd 3 16 4 100 4
    pause
    popd
    exit /b 1
)
echo Bitstream: %W4BUILD%
echo xsdb:      %XSDB%
for %%m in (dn_d10_c32_us_fx_qat dn_d10_c32_us_mo_fx_qat dn_d10_c64_us_es_qat dn_d7_c32_es) do (
    echo.
    echo ===== %%m =====
    python scripts\run_denoise.py --model %%m --xsdb "%XSDB%" --build "%W4BUILD%" --w4 --fclk 50 --images 05.png --out build\w4_%%m
    if errorlevel 1 (
        echo.
        echo STOPPED at %%m. The lines above say why.
        pause
        popd
        exit /b 1
    )
    copy /y build\w4_%%m\report.json denoise\board_runs\%%m_05_w4.json >nul
)
echo.
echo All four ran. Compare with the prediction made before this bitstream existed:
echo   python denoise\compare_w4.py
echo Then send the results:
echo   git add denoise/board_runs denoise/w4_measured.json
echo   git commit -m "Board runs on the four-wide window port"
echo   git push
pause
popd
exit /b 0
