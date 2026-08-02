@echo off
REM ============================================================
REM  run_scheduler.bat  --  Run DAGI scheduled tasks
REM
REM  Usage:
REM    run_scheduler.bat              (run all due tasks)
REM    run_scheduler.bat --dry-run    (show what would run, no execution)
REM
REM  To wire into Windows Task Scheduler:
REM    Program:   C:\Users\alexr\Driverless_AGI\run_scheduler.bat
REM    Start in:  C:\Users\alexr\Driverless_AGI
REM    Trigger:   e.g. Daily at 08:00, or Hourly
REM
REM  Running more often than your shortest interval is harmless —
REM  the scheduler checks due times and skips tasks that aren't ready.
REM ============================================================

cd /d "%~dp0"
set PYTHONUTF8=1

conda run --no-capture-output -n dagi python -m scheduler.runner %*

if %ERRORLEVEL% neq 0 (
    echo [DAGI Scheduler] Exited with error code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)
