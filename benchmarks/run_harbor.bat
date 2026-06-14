@echo off

REM ============================================================
REM  run_harbor.bat  --  Run DAGI against Harbor benchmarks
REM
REM  Usage:
REM    run_harbor.bat                               (full suite)
REM    run_harbor.bat --n-tasks 5                   (limit task count)
REM    run_harbor.bat --n-concurrent 4              (parallel)
REM
REM  Override model:
REM    set DAGI_BENCH_MODEL=claude-sonnet-openrouter
REM    run_harbor.bat
REM
REM  Override dataset:
REM    set HARBOR_DATASET=terminal-bench/terminal-bench-2
REM
REM  List datasets:   harbor datasets list
REM                   https://hub.harborframework.com/datasets
REM
REM  Local model (default): llama.cpp must be running on localhost:8080
REM    llama-server --host 0.0.0.0 --port 8080
REM      --model /models/E4B-Gemma4-it-vl-HERE-DECKARD4-Q8_0.gguf
REM ============================================================

REM -- Resolve conda executable (works whether or not conda is in PATH) --------
set CONDA_BIN=%USERPROFILE%\miniconda3\Scripts\conda.exe
if not exist "%CONDA_BIN%" set CONDA_BIN=%CONDA_EXE%
if not exist "%CONDA_BIN%" (
    echo [DAGI] ERROR: conda not found. Set CONDA_EXE or install miniconda3.
    exit /b 1
)

REM -- Defaults (only applied when var is unset or empty) ----------------------
if "%DAGI_BENCH_MODEL%"=="" set DAGI_BENCH_MODEL=local-llamacpp
if "%HARBOR_DATASET%"=="" set HARBOR_DATASET=terminal-bench/terminal-bench-2

REM -- Change to project root so 'benchmarks.harbor.agent' is importable ---------
cd /d "%~dp0.."

REM -- Force UTF-8 to prevent UnicodeEncodeError on box-drawing chars ----------
set PYTHONUTF8=1

echo [DAGI] Harbor benchmark runner
echo [DAGI] Model   : %DAGI_BENCH_MODEL%
echo [DAGI] Dataset : %HARBOR_DATASET%
echo [DAGI] Args    : %*
echo.

"%CONDA_BIN%" run -n dagi harbor run --dataset "%HARBOR_DATASET%" --agent-import-path benchmarks.harbor.agent:DagiAgent --jobs-dir benchmarks/jobs --n-concurrent 1 %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [DAGI] Run failed with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)
echo.
echo [DAGI] Run complete.
