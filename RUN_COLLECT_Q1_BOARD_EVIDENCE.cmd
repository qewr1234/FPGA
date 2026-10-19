@echo off
rem Copy the raw reports of the W=4 canary and three-layout (Original, Frozen,
rem Multi-start) board runs from build\ into denoise\board_runs\q1_layouts, then
rem commit and push them. Run it on the PC that ran the board, from the repo root,
rem on branch claude/determined-keller-qurd64.
rem
rem   RUN_COLLECT_Q1_BOARD_EVIDENCE.cmd
rem
rem Copies JSON / Markdown / log files only; PNG, NPZ and the _io board files are
rem listed with their SHA-256 in MANIFEST.json, not copied. build\ is not changed.
setlocal
pushd "%~dp0"
for /f %%b in ('git rev-parse --abbrev-ref HEAD') do set "BR=%%b"
if not "%BR%"=="claude/determined-keller-qurd64" (
  echo On branch %BR%. First run:
  echo   git fetch origin
  echo   git checkout claude/determined-keller-qurd64
  echo   git pull origin claude/determined-keller-qurd64
  popd & exit /b 1
)
python scripts\collect_q1_board_evidence.py || (popd & exit /b 1)
git add denoise\board_runs\q1_layouts || (popd & exit /b 1)
git commit -m "Board evidence: raw reports of the W=4 canary and three-layout runs (from build/)" || (popd & exit /b 1)
git push origin claude/determined-keller-qurd64
popd
