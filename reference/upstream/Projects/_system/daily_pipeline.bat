@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0.."

rem ====================================================================
rem  Daily host pipeline (merged 2026-09-27)
rem  Replaces three separate Task Scheduler entries:
rem    Market_Data_Fetcher (08:30) + Host_Signals (08:45) + website (09:15)
rem  One chain, strict order, so a late wake-up can no longer run the
rem  steps out of order (2026-09-27: all three fired at 11:55 together,
rem  website validated against yesterday's manifest and Host_Signals
rem  read the old manifest before the fetcher had finished).
rem
rem  Order:  [1] fetch -> [2] signals -> [3] paper portfolio -> [4] validate
rem          -> [5] rescan -> [6] three-year coverage -> [7] build site -> [8] push
rem  (renumbered 1..8 on 2026-10-02; no fractional step ids)
rem
rem  NOTE: keep this file pure ASCII, no BOM, CRLF line endings.
rem  cmd.exe parses .bat in the system ANSI codepage (GBK here); a BOM
rem  or CJK text corrupts lines and silently blanks %LOG%. (2026-08-14)
rem ====================================================================

set "LOG=%~dp0last_run.log"
echo ==================================================== > "%LOG%"
echo  run at %DATE% %TIME% >> "%LOG%"
echo ==================================================== >> "%LOG%"

rem Pinned interpreter. Never fall back to another Python (py launcher
rem defaults to 3.14 here). If this path is gone, stop and fix it here.
set "PY=C:\Python311\python.exe"
if not exist "%PY%" goto :fail_python
"%PY%" --version >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_python
"%PY%" -c "import sys; print('interpreter:', sys.executable)" >> "%LOG%" 2>&1

rem ---- [1/8] market data ------------------------------------------
rem exit 0 = all ok; 2 = some tickers failed (manifest still written,
rem continue -- step 3 --strict will refuse to publish incomplete data);
rem 1 = fatal (no manifest) -> stop the whole chain.
echo [1/8] fetching market data... >> "%LOG%"
"%PY%" _system\scripts\market_data_fetcher.py >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo   fetcher exit code: %RC% >> "%LOG%"
if "%RC%"=="1" goto :fail_fetch
if %RC% GTR 2 goto :fail_fetch

rem ---- [2/8] technical signals ------------------------------------
rem Reads _data_status.json written by step 1, stamps its own output
rem with source_manifest_generated_at so the scanner can verify the link.
rem exit 2 = some tickers failed (file still written); 1 = no file.
rem The website does not need signals, so do not stop the chain here;
rem just record it. The scanner will see the stale/missing file itself.
echo [2/8] computing technical signals... >> "%LOG%"
"%PY%" _system\host_pipeline\host_signals.py >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo   host_signals exit code: %RC% >> "%LOG%"
if not "%RC%"=="0" echo   WARNING: host_signals did not fully succeed (see above). >> "%LOG%"


rem ---- [3/8] paper portfolio (strategy: undervalued + growth) ------
rem Runs BEFORE the strict validation gate on purpose: on a fetch failure
rem the publish is blocked but the paper book must still record the day.
rem Fills use fresh closes only: a ticker trades only if its close is
rem <= 3 calendar days old AND not behind its market index (SPX/HSI/
rem CSI300); otherwise that day only revalues NAV, and a later same-day
rem rerun may still trade. (2026-10-03: the old 7-day window let the
rem 9/30 run fill at 9/25 closes.)
rem Rewrites _system\paper_portfolio\dashboard.html. Warn only. 2026-09-30.
echo [3/8] updating paper portfolio... >> "%LOG%"
"%PY%" _system\scripts\paper_portfolio.py >> "%LOG%" 2>&1
if not "%ERRORLEVEL%"=="0" echo   WARNING: paper_portfolio did not succeed (see above). >> "%LOG%"

rem ---- [4/8] validate --------------------------------------------
echo [4/8] validating market data... >> "%LOG%"
"%PY%" _system\scripts\validate_market_data.py --strict >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_market

rem ---- [5/8] rescan dossier registry -----------------------------
echo [5/8] rescanning dossier registry... >> "%LOG%"
"%PY%" _system\scripts\dossier_orchestrator.py rescan >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_rescan

echo [6/8] checking three-year valuation coverage... >> "%LOG%"
"%PY%" _system\scripts\validate_three_year_coverage.py >> "%LOG%" 2>&1

rem ---- [6.5/8] archive housekeeping (non-blocking) ------------
rem Moves dated files older than 31 days and .bak backups older than 3 days
rem into _system\_archive\. Failure here never blocks the publish.
echo [6.5/8] archiving old files and stale .bak backups... >> "%LOG%"
"%PY%" _system\scripts\archive_old.py --apply >> "%LOG%" 2>&1

rem ---- [7/8] build site ------------------------------------------
echo [7/8] rebuilding website... >> "%LOG%"
"%PY%" _system\scripts\build_site.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_build

rem ---- [8/8] publish ---------------------------------------------
echo [8/8] publishing to GitHub... >> "%LOG%"
pushd website_deploy
if errorlevel 1 goto :fail_git_no_popd

git rev-parse --is-inside-work-tree >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_git

git add -A >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_git

git diff --cached --quiet
if errorlevel 2 goto :fail_git
if errorlevel 1 goto :commit
echo   no content changes; commit skipped. >> "%LOG%"
goto :push

:commit
git commit -m "auto update %DATE% %TIME%" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_git

:push
git push >> "%LOG%" 2>&1
if errorlevel 1 goto :fail_git
popd

echo SUCCESS: GitHub push completed. Cloudflare deployment was triggered; deployment result must be checked separately. >> "%LOG%"
exit /b 0

:fail_git
popd
:fail_git_no_popd
set "FAIL_STEP=Git publish"
goto :failed

:fail_python
set "FAIL_STEP=Python interpreter"
goto :failed

:fail_fetch
set "FAIL_STEP=Market data fetch (fatal, no manifest written)"
goto :failed

:fail_market
set "FAIL_STEP=Market data validation"
goto :failed

:fail_rescan
set "FAIL_STEP=Dossier registry rescan"
goto :failed

:fail_build
set "FAIL_STEP=Website build"
goto :failed

:failed
echo FAILED: %FAIL_STEP%. Git push was not completed. See the error above. >> "%LOG%"
exit /b 1
