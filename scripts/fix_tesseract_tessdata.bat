@echo off
REM scripts\fix_tesseract_tessdata.bat — Fix ocrmypdf's "Can't open hocr" /
REM TesseractConfigError on Windows conda envs.
REM
REM Some conda-forge tesseract builds split tessdata across two directories:
REM   %CONDA_PREFIX%\share\tessdata            -- language .traineddata files
REM                                                (this is what TESSDATA_PREFIX
REM                                                 gets set to by the env's
REM                                                 activate script)
REM   %CONDA_PREFIX%\Library\share\tessdata    -- configs\ and tessconfigs\
REM                                                (hocr, alto, etc.)
REM so tesseract can find language data but not the "hocr" config file
REM ocrmypdf requires, and OCR fails before ever reaching docling.
REM
REM Run this with the target conda env active:
REM   conda activate dagi
REM   scripts\fix_tesseract_tessdata.bat

setlocal enabledelayedexpansion

if "%CONDA_PREFIX%"=="" (
    echo ERROR: No active conda environment detected.
    echo Run "conda activate ^<env^>" first, then re-run this script.
    exit /b 1
)

set "SRC=%CONDA_PREFIX%\Library\share\tessdata"
set "DST=%CONDA_PREFIX%\share\tessdata"

if exist "%DST%\configs\hocr" (
    echo [OK] "%DST%\configs\hocr" already present -- nothing to do.
    exit /b 0
)

if not exist "%SRC%\configs\hocr" (
    echo ERROR: Expected tesseract configs at "%SRC%\configs" but "hocr" was not found there.
    echo This env's tesseract package layout doesn't match what this script expects --
    echo inspect "%CONDA_PREFIX%" manually.
    exit /b 1
)

if not exist "%DST%" (
    echo ERROR: Expected a tessdata directory at "%DST%" ^(the TESSDATA_PREFIX target^) but it does not exist.
    exit /b 1
)

echo Copying tesseract configs/tessconfigs into "%DST%" ...
xcopy /E /I /Y "%SRC%\configs" "%DST%\configs" >nul
if exist "%SRC%\tessconfigs" (
    xcopy /E /I /Y "%SRC%\tessconfigs" "%DST%\tessconfigs" >nul
)

if exist "%DST%\configs\hocr" (
    echo [OK] Fixed -- "%DST%\configs\hocr" is now present.
    exit /b 0
) else (
    echo ERROR: Copy ran but "%DST%\configs\hocr" is still missing.
    exit /b 1
)

endlocal
