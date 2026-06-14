@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM  run_terminus2.bat  —  Run Harbor's built-in Terminus 2 agent
REM                        against terminal-bench/terminal-bench-2
REM
REM  Usage:
REM    run_terminus2.bat                               (full suite)
REM    run_terminus2.bat --task-id <id>                (single task)
REM    run_terminus2.bat --n-concurrent 4              (parallel)
REM    run_terminus2.bat -d <org>/<name>               (specific dataset)
REM
REM  Default: local llama.cpp server (must be running on localhost:8080)
REM    llama-server --host 0.0.0.0 --port 8080 ^
REM      --model /models/E4B-Gemma4-it-vl-HERE-DECKARD4-Q8_0.gguf
REM
REM  Override model (LiteLLM format):
REM    set TERMINUS2_MODEL=openai//models/E4B-Gemma4-it-vl-HERE-DECKARD4-Q8_0.gguf
REM    set TERMINUS2_MODEL=openrouter/anthropic/claude-sonnet-4-6
REM
REM  Override API base:
REM    set TERMINUS2_API_BASE=http://localhost:8080/v1
REM
REM  Override dataset:
REM    set HARBOR_DATASET=terminal-bench/terminal-bench-2
REM
REM  Cloud model example (OpenRouter):
REM    set TERMINUS2_MODEL=openrouter/anthropic/claude-sonnet-4-6
REM    set TERMINUS2_API_BASE=
REM    run_terminus2.bat --n-concurrent 2
REM ============================================================

REM --- Defaults -----------------------------------------------
if "%TERMINUS2_MODEL%"==""    set TERMINUS2_MODEL=openai//models/E4B-Gemma4-it-vl-HERE-DECKARD4-Q8_0.gguf
if "%TERMINUS2_API_BASE%"=="" set TERMINUS2_API_BASE=http://localhost:8080/v1
if "%HARBOR_DATASET%"==""     set HARBOR_DATASET=terminal-bench/terminal-bench-2

REM --- LiteLLM needs a non-empty API key for openai/ prefix ---
REM     llama.cpp accepts any Bearer token; set dummy only if unset.
if "%OPENAI_API_KEY%"=="" set OPENAI_API_KEY=dummy

echo [Terminus 2] Harbor benchmark runner
echo [Terminus 2] Model    : %TERMINUS2_MODEL%
echo [Terminus 2] API base : %TERMINUS2_API_BASE%
echo [Terminus 2] Dataset  : %HARBOR_DATASET%
echo [Terminus 2] Args     : %*
echo.

REM Build the api_base kwarg conditionally (omit for cloud routes like openrouter/)
set AK_API_BASE=
if not "%TERMINUS2_API_BASE%"=="" set AK_API_BASE=--ak api_base=!TERMINUS2_API_BASE!

conda run -n dagi harbor run ^
  --agent terminus-2 ^
  --model %TERMINUS2_MODEL% ^
  --dataset %HARBOR_DATASET% ^
  !AK_API_BASE! ^
  --n-concurrent 1 ^
  %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [Terminus 2] Run failed with exit code %ERRORLEVEL%.
    exit /b %ERRORLEVEL%
)
echo.
echo [Terminus 2] Run complete.
