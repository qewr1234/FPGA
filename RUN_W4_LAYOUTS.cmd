@echo off
rem PROTOCOL_2 board runs (bankperm\PROTOCOL_2.md): B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat)
rem on the W=4 bitstream, layouts Original, Frozen, Multi-start and Skew, Set12 05, 06, 07, 08.png.
rem
rem   RUN_W4_LAYOUTS.cmd [xsdb] [allow-other-bitstream]
rem        xsdb defaults to C:/Vivado/2026.1/Vivado/bin/xsdb.bat; allow-other-bitstream accepts
rem        a bitstream that is not the earlier W=4 canary's (see step 1)
rem
rem 1. Unpacks the Frozen and Multi-start ZIPs to build\layout_exports\frozen and \multistart
rem    (bankperm\prepare_layouts.py, Python zipfile), writes the skew export to
rem    build\layout_exports\skew (bankperm\export_layout.py) and checks every file's SHA-256
rem    (prepare_layouts.py --verify --require-check: also against bankperm\skew_export_check.json).
rem    Then pins the setup in denoise\board_runs\q1_layouts2\setup.json (prepare_layouts.py
rem    --bitstream): bankperm\board_prediction_2.json must be committed and unchanged (git),
rem    every config.bin of the four layouts must be the one it was predicted with, and the
rem    bitstream must be the earlier W=4 canary's (bankperm\board_transcribed.json) unless
rem    allow-other-bitstream is given. A rerun refuses a bitstream, prediction, export or
rem    driver file that differs from what setup.json pinned.
rem 2. 16 board runs, --w4 --mode 1 --fclk 50 --tile 65536, each to
rem    denoise\board_runs\q1_layouts2\LAYOUT_STEM\report.json: 05.png Original first as
rem    the canary, then 05.png Skew, then the rest. Stops at the first failure. The canary is
rem    compared with its prediction layer by layer before anything else runs; if a layer
rem    misses, it asks whether to carry on. A run whose report.json is there and passes
rem    bankperm\compare_board_2.py's checks (core ID 0x4d410303, 50 MHz, its layout's
rem    export, ...) is skipped, so running this again after a failure carries on where it
rem    stopped; the folder of an unfinished run is first moved to
rem    denoise\board_runs\q1_layouts2_attempts (kept, not deleted). To redo a finished run,
rem    move its folder away first.
rem 3. bankperm\compare_board_2.py: the runs against bankperm\board_prediction_2.json.
rem 4. Prints the git lines to send the results. Nothing is pushed from here.
rem
rem About six minutes per run on 05-07.png (256x256, ten layers over JTAG) and about four times
rem that on 08.png (512x512, run last): roughly two and a half hours for all 16.
rem Needs a build\zed_v4_p16_t4_w4_* bitstream and uses the newest one (as RUN_W4_DENOISE.cmd).
setlocal EnableDelayedExpansion
pushd "%~dp0"
set "XSDB=%~1"
if "%XSDB%"=="" set "XSDB=C:/Vivado/2026.1/Vivado/bin/xsdb.bat"
set "MODEL=dn_d10_c32_us_fx_qat"
set "RUNS=denoise\board_runs\q1_layouts2"
set "STOP="
set "ALLOWBIT="
if /i "%~2"=="allow-other-bitstream" set "ALLOWBIT=--allow-other-bitstream"
if not "%~2"=="" if not defined ALLOWBIT (
    echo The second argument can only be allow-other-bitstream, not %~2
    set "STOP=an unknown second argument"
)
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
    set "STOP=no W=4 bitstream"
)
if not defined STOP (
    python -c "import os, sys; sys.exit(0 if os.path.isfile(sys.argv[1]) else 1)" "%XSDB%"
    if errorlevel 1 (
        echo xsdb is not at !XSDB!. Give its path as the first argument.
        set "STOP=no xsdb"
    )
)
if not defined STOP (
    echo Bitstream: !W4BUILD!
    echo xsdb:      !XSDB!
    echo.
    echo ===== 1. layout exports =====
    python bankperm\prepare_layouts.py --out build\layout_exports
    if errorlevel 1 set "STOP=unpacking the Frozen and Multi-start exports"
)
if not defined STOP (
    python bankperm\export_layout.py --layout skew --model %MODEL% --out build\layout_exports\skew
    if errorlevel 1 set "STOP=writing the skew export"
)
if not defined STOP (
    python bankperm\prepare_layouts.py --verify build\layout_exports --require-check
    if errorlevel 1 set "STOP=checking the layout exports"
)
if not defined STOP (
    python bankperm\prepare_layouts.py --bitstream "%W4BUILD%" --exports build\layout_exports --record %RUNS%\setup.json %ALLOWBIT%
    if errorlevel 1 set "STOP=pinning the prediction, the exports and the bitstream"
)
if not defined STOP (
    echo.
    echo ===== 2. board runs =====
)
for %%r in ("original 05.png" "skew 05.png" "frozen 05.png" "multistart 05.png" "original 06.png" "skew 06.png" "frozen 06.png" "multistart 06.png" "original 07.png" "skew 07.png" "frozen 07.png" "multistart 07.png" "original 08.png" "skew 08.png" "frozen 08.png" "multistart 08.png") do if not defined STOP (
    for /f "tokens=1,2" %%a in ("%%~r") do (
        set "EXP=--export-dir build\layout_exports\%%a"
        if "%%a"=="original" set "EXP="
        set "OUT=%RUNS%\%%a_%%~nb"
        python bankperm\compare_board_2.py --run-state "!OUT!" --layout %%a --image %%b
        if errorlevel 11 (
            set "STOP=%%a %%b: checking its folder"
        ) else if errorlevel 10 (
            echo %%a %%b: already done, skipped
        ) else if errorlevel 1 (
            set "STOP=%%a %%b: checking its folder"
        ) else (
            echo.
            echo ===== %%a %%b =====
            python scripts\run_denoise.py --model %MODEL% !EXP! --xsdb "%XSDB%" --build "%W4BUILD%" --w4 --mode 1 --fclk 50 --set Set12 --images %%b --tile 65536 --out "!OUT!" --board-dir "build\q1_layouts2_io\%%a_%%~nb"
            if errorlevel 1 (
                set "STOP=%%a %%b: the board run"
            ) else (
                python bankperm\compare_board_2.py --check-run "!OUT!" --layout %%a --image %%b
                if not errorlevel 10 set "STOP=%%a %%b: its report.json does not pass the checks"
            )
        )
        if not defined STOP if "%%a %%b"=="original 05.png" (
            echo.
            echo ===== canary: original 05.png against its prediction =====
            python bankperm\compare_board_2.py --canary "!OUT!" --layout %%a --image %%b
            if errorlevel 12 (
                set "STOP=the canary check of original 05.png"
            ) else if errorlevel 11 (
                echo.
                echo The canary original 05.png misses the prediction on the layers marked MISS above.
                echo The earlier W=4 run of this same case matched every layer, so check the setup first:
                echo the PL clock, the bitstream and the board. The run is kept as it is.
                choice /c YN /m "Carry on with the other 15 runs anyway"
                if errorlevel 2 set "STOP=the canary original 05.png misses the prediction and you chose to stop"
            ) else if errorlevel 10 (
                echo canary: every layer exact, carrying on
            ) else (
                set "STOP=the canary check of original 05.png"
            )
        )
    )
)
if defined STOP (
    echo.
    echo STOPPED: !STOP!. The lines above say why.
    echo Run RUN_W4_LAYOUTS.cmd again to carry on: finished runs are skipped.
    echo Runs finished so far are compared with:  python bankperm\compare_board_2.py
    pause
    popd
    exit /b 1
)
echo.
echo ===== 3. measured against the prediction =====
python bankperm\compare_board_2.py
echo.
echo ===== 4. send the results =====
echo   git add bankperm/board_measured_2.json denoise/board_runs/q1_layouts2 ":(exclude)*.npz"
if exist denoise\board_runs\q1_layouts2_attempts echo   git add denoise/board_runs/q1_layouts2_attempts ":(exclude)*.npz"
echo   git commit -m "PROTOCOL_2 board runs: four layouts on Set12 05-08, W=4 bitstream"
echo   git push
pause
popd
exit /b 0
