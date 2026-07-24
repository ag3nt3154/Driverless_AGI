@echo off
REM ============================================================
REM  dagi_run.bat  --  Double-click launcher for Driverless AGI
REM
REM  1. Opens a Windows Terminal window
REM  2. Activates the conda-packed environment "dagi_env"
REM     (expected as a sibling folder next to this repo, i.e.
REM     {parent_folder}\dagi_env, {parent_folder}\driverless_agi)
REM  3. Runs dagi_launch.py, which prompts for a model + verbose
REM     setting and then starts tui.py
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "ENV_DIR=%SCRIPT_DIR%..\dagi_env"

if not exist "%ENV_DIR%\Scripts\activate.bat" (
    echo [DAGI] Could not find conda-packed environment at "%ENV_DIR%".
    echo [DAGI] Expected layout: {parent_folder}\dagi_env and {parent_folder}\driverless_agi
    pause
    exit /b 1
)

where wt.exe >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start "" wt.exe -d "%SCRIPT_DIR%" cmd /k "call "%ENV_DIR%\Scripts\activate.bat" && python dagi_launch.py"
) else (
    start "" cmd /k "cd /d "%SCRIPT_DIR%" && call "%ENV_DIR%\Scripts\activate.bat" && python dagi_launch.py"
)
