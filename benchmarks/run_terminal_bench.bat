@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  run_terminal_bench.bat  —  Run DAGI against Terminal-bench 2
REM
REM  Usage:
REM    benchmarks\run_terminal_bench.bat                     (full suite)
REM    benchmarks\run_terminal_bench.bat --task-id <id>      (single task)
REM    benchmarks\run_terminal_bench.bat --n-concurrent 4    (parallel)
REM
REM  Override model before running:
REM    set DAGI_BENCH_MODEL=claude-opus-openrouter
REM ============================================================

if "%DAGI_BENCH_MODEL%"=="" set DAGI_BENCH_MODEL=claude-sonnet-openrouter

echo [DAGI] Terminal-bench 2 runner
echo [DAGI] Model  : %DAGI_BENCH_MODEL%
echo [DAGI] Config : config_benchmark.yaml
echo [DAGI] Args   : %*
echo.

conda run -n dagi tb run ^
  --dataset terminal-bench-core==head ^
  --agent-import-path benchmarks.terminal_bench.agent:DagiAgent ^
  %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [DAGI] Run failed with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)

echo.
echo [DAGI] Run complete.
