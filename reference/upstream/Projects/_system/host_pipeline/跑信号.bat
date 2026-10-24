@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
set "LOG=%~dp0host_signals_last_run.log"
echo ==================================================== > "%LOG%"
echo  host_signals run at %DATE% %TIME% >> "%LOG%"
echo ==================================================== >> "%LOG%"

where py >nul 2>nul && (py -3.11 host_signals.py >> "%LOG%" 2>&1) || (python host_signals.py >> "%LOG%" 2>&1)

echo. >> "%LOG%"
echo exit code: %ERRORLEVEL% >> "%LOG%"
echo done. >> "%LOG%"
