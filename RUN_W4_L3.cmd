@echo off
rem PROTOCOL_2 addendum board runs (bankperm\PROTOCOL_2_ADDENDUM.md): B-32 ReLU + QAT s1
rem (dn_d10_c32_us_fx_qat), layout L3 (skew + relabeling, bankperm\perms_2.json), on the W=4
rem bitstream, Set12 05, 06, 07, 08.png. Run it after RUN_W4_LAYOUTS.cmd has finished: one board.
rem
rem   RUN_W4_L3.cmd [xsdb] [allow-other-bitstream] [allow-unfinished-layouts]
rem        xsdb defaults to C:/Vivado/2026.1/Vivado/bin/xsdb.bat; allow-other-bitstream accepts
rem        a bitstream that is not the earlier W=4 canary's (see step 1); allow-unfinished-layouts
rem        runs although RUN_W4_LAYOUTS.cmd has not finished its 16 runs (see step 1). Both only
rem        on purpose, in either order after xsdb.
rem
rem Nothing of RUN_W4_LAYOUTS.cmd's changes: its folders (denoise\board_runs\q1_layouts2,
rem build\layout_exports\frozen, multistart, skew), its prediction and its scripts are only read.
rem
rem 1. Writes the L3 export to build\layout_exports\l3 (bankperm\export_layout.py --orders
rem    bankperm\perms_2.json) and checks every file's SHA-256 (bankperm\prepare_l3.py --verify
rem    --require-check: a fresh export, and the hashes of bankperm\l3_export_check.json, written
rem    on the analysis machine by bankperm\check_l3_export.py). Then pins the setup in
rem    denoise\board_runs\q1_layouts3\setup.json (prepare_l3.py --bitstream):
rem    bankperm\board_prediction_3.json and bankperm\l3_export_check.json must be committed and
rem    unchanged (git), every config.bin of the L3 export must be the one it was predicted with,
rem    and the bitstream must be the earlier W=4 canary's (bankperm\board_transcribed.json) and
rem    the one denoise\board_runs\q1_layouts2\setup.json pinned (when it is there) unless
rem    allow-other-bitstream is given. RUN_W4_LAYOUTS.cmd must have finished: its setup.json
rem    and all 16 of its runs there and passing bankperm\compare_board_2.py's checks, unless
rem    allow-unfinished-layouts is given. The L3 tools (this script, prepare_l3.py,
rem    compare_board_3.py and what they import) must be the files l3_export_check.json records.
rem    A rerun refuses a bitstream, prediction, export, driver or tool file that differs from
rem    what setup.json pinned.
rem 2. 4 board runs, --w4 --mode 1 --fclk 50 --tile 65536, each to
rem    denoise\board_runs\q1_layouts3\l3_STEM\report.json, 05.png first. Stops at the first
rem    failure. 05.png is compared with its prediction layer by layer before the others run; if
rem    a layer misses, it asks whether to carry on. A run whose report.json is there and passes
rem    bankperm\compare_board_3.py's checks (core ID 0x4d410303, 50 MHz, the L3 export,
rem    conv2..conv9 reordered, ...) is skipped, so running this again after a failure carries on
rem    where it stopped; the folder of an unfinished run is first moved to
rem    denoise\board_runs\q1_layouts3_attempts (kept, not deleted). To redo a finished run,
rem    move its folder away first.
rem 3. bankperm\compare_board_3.py: the runs against bankperm\board_prediction_3.json, and against
rem    the Original and Skew runs of the same images in denoise\board_runs\q1_layouts2.
rem 4. Prints the git lines to send the results. Nothing is pushed from here.
rem
rem About six minutes per run on 05-07.png and about four times that on 08.png (run last):
rem roughly 45 minutes for all 4.
rem Needs a build\zed_v4_p16_t4_w4_* bitstream and uses the newest one (as RUN_W4_LAYOUTS.cmd).
setlocal EnableDelayedExpansion
pushd "%~dp0"
set "XSDB=%~1"
if "%XSDB%"=="" set "XSDB=C:/Vivado/2026.1/Vivado/bin/xsdb.bat"
set "MODEL=dn_d10_c32_us_fx_qat"
set "RUNS=denoise\board_runs\q1_layouts3"
set "L3EXP=build\layout_exports\l3"
set "STOP="
set "ALLOWBIT="
set "ALLOWQ2="
for %%a in (%2 %3) do if not "%%~a"=="" (
    if /i "%%~a"=="allow-other-bitstream" (
        set "ALLOWBIT=--allow-other-bitstream"
    ) else if /i "%%~a"=="allow-unfinished-layouts" (
        set "ALLOWQ2=--allow-unfinished-layouts"
    ) else (
        echo After xsdb only allow-other-bitstream and allow-unfinished-layouts can be given, not %%~a
        set "STOP=an unknown argument"
    )
)
if not "%~4"=="" (
    echo At most three arguments: xsdb, allow-other-bitstream, allow-unfinished-layouts
    set "STOP=too many arguments"
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
    echo ===== 1. L3 export =====
    python bankperm\export_layout.py --layout skew --model %MODEL% --orders bankperm\perms_2.json --out %L3EXP%
    if errorlevel 1 set "STOP=writing the L3 export"
)
if not defined STOP (
    python bankperm\prepare_l3.py --verify %L3EXP% --require-check
    if errorlevel 1 set "STOP=checking the L3 export"
)
if not defined STOP (
    python bankperm\prepare_l3.py --bitstream "%W4BUILD%" --export %L3EXP% --record %RUNS%\setup.json %ALLOWBIT% %ALLOWQ2%
    if errorlevel 1 set "STOP=pinning the prediction, the export and the bitstream"
)
if not defined STOP (
    echo.
    echo ===== 2. board runs =====
)
for %%b in (05.png 06.png 07.png 08.png) do if not defined STOP (
    set "OUT=%RUNS%\l3_%%~nb"
    python bankperm\compare_board_3.py --run-state "!OUT!" --image %%b
    if errorlevel 11 (
        set "STOP=l3 %%b: checking its folder"
    ) else if errorlevel 10 (
        echo l3 %%b: already done, skipped
    ) else if errorlevel 1 (
        set "STOP=l3 %%b: checking its folder"
    ) else (
        echo.
        echo ===== l3 %%b =====
        python scripts\run_denoise.py --model %MODEL% --export-dir %L3EXP% --xsdb "%XSDB%" --build "%W4BUILD%" --w4 --mode 1 --fclk 50 --set Set12 --images %%b --tile 65536 --out "!OUT!" --board-dir "build\q1_layouts3_io\l3_%%~nb"
        if errorlevel 1 (
            set "STOP=l3 %%b: the board run"
        ) else (
            python bankperm\compare_board_3.py --check-run "!OUT!" --image %%b
            if not errorlevel 10 set "STOP=l3 %%b: its report.json does not pass the checks"
        )
    )
    if not defined STOP if "%%b"=="05.png" (
        echo.
        echo ===== first run: l3 05.png against its prediction =====
        python bankperm\compare_board_3.py --canary "!OUT!" --image %%b
        if errorlevel 12 (
            set "STOP=the check of l3 05.png against its prediction"
        ) else if errorlevel 11 (
            echo.
            echo l3 05.png misses the prediction on the layers marked MISS above.
            echo If the Original and Skew runs of RUN_W4_LAYOUTS.cmd matched theirs, check the setup
            echo first: the PL clock, the bitstream and the board. The run is kept as it is.
            choice /c YN /m "Carry on with the other 3 runs anyway"
            if errorlevel 2 (
                set "STOP=l3 05.png misses the prediction and you chose to stop"
            ) else if not errorlevel 1 (
                set "STOP=l3 05.png misses the prediction and no Y was given"
            )
        ) else if errorlevel 10 (
            echo l3 05.png: every layer exact, carrying on
        ) else (
            set "STOP=the check of l3 05.png against its prediction"
        )
    )
)
if defined STOP (
    echo.
    echo STOPPED: !STOP!. The lines above say why.
    echo Run RUN_W4_L3.cmd again to carry on: finished runs are skipped.
    echo Runs finished so far are compared with:  python bankperm\compare_board_3.py
    pause
    popd
    exit /b 1
)
echo.
echo ===== 3. measured against the prediction, the Original and the Skew =====
python bankperm\compare_board_3.py
echo.
echo ===== 4. send the results =====
echo   git add bankperm/board_measured_3.json denoise/board_runs/q1_layouts3 ":(exclude)*.npz"
if exist denoise\board_runs\q1_layouts3_attempts echo   git add denoise/board_runs/q1_layouts3_attempts ":(exclude)*.npz"
echo   git commit -m "PROTOCOL_2 addendum board runs: L3 on Set12 05-08, W=4 bitstream"
echo   git push
pause
popd
exit /b 0
