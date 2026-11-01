@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title FX-ARS
set "PYTHONUTF8=1"

set "PYEXE="
if defined FXARS_PYTHON if exist "%FXARS_PYTHON%" set "PYEXE=%FXARS_PYTHON%"

if not defined PYEXE (
    for %%P in (python.exe) do if not defined PYEXE set "PYEXE=%%~$PATH:P"
)

if not defined PYEXE (
    set "BUNDLED=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if exist "!BUNDLED!" set "PYEXE=!BUNDLED!"
)

if not defined PYEXE (
    for %%V in (313 312 311) do (
        if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
            set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
)

if not defined PYEXE (
    echo.
    echo [FX-ARS] Python 3.11+ not found.
    echo Install Python 3.11 or newer, or set FXARS_PYTHON to python.exe
    echo.
    if not defined FXARS_NO_PAUSE pause
    exit /b 1
)

"%PYEXE%" "scripts\launcher.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [FX-ARS] exited with code %RC%.
    if not defined FXARS_NO_PAUSE pause
)
endlocal & exit /b %RC%
