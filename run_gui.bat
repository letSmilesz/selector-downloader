@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
title lib.me_downloader

rem PROJECT_DIR = folder of this file; PARENT_DIR = its parent.
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
for %%I in ("%PROJECT_DIR%\..") do set "PARENT_DIR=%%~fI"
set "APP=%PROJECT_DIR%\frontend\main_window.py"
set "LOGDIR=%PROJECT_DIR%\logs"
set "GUI_LOG=%LOGDIR%\gui_console.log"

rem --- Locate venv: parent first, then project. Override: set MLD_PYTHON=... ---
set "PYEXE="
if defined MLD_PYTHON set "PYEXE=%MLD_PYTHON%"
if not defined PYEXE if exist "%PARENT_DIR%\.venv\Scripts\pythonw.exe" set "PYEXE=%PARENT_DIR%\.venv\Scripts\pythonw.exe"
if not defined PYEXE if exist "%PROJECT_DIR%\.venv\Scripts\pythonw.exe" set "PYEXE=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"
if not defined PYEXE if exist "%PARENT_DIR%\venv\Scripts\pythonw.exe" set "PYEXE=%PARENT_DIR%\venv\Scripts\pythonw.exe"
if not defined PYEXE if exist "%PROJECT_DIR%\venv\Scripts\pythonw.exe" set "PYEXE=%PROJECT_DIR%\venv\Scripts\pythonw.exe"
if not defined PYEXE (
    echo [ERROR] pythonw.exe not found in parent or project venv.
    echo Create a venv or set MLD_PYTHON=C:\path\to\pythonw.exe
    pause
    exit /b 1
)
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYCON=%PYDIR%python.exe"
if not exist "%APP%" (
    echo [ERROR] main_window.py not found: %APP%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "PATH=%PYDIR%;%PATH%"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem --- Silent mode (called by run_gui.vbs): hidden window, GUI only ---
if /I "%~1"=="--silent" goto silent

rem --- Console mode (double-click): errors visible, pause on failure ---
"%PYCON%" "%APP%"
set "EXIT_CODE=%ERRORLEVEL%"
if %EXIT_CODE% neq 0 (
    echo.
    echo [ERROR] main_window.py exited with code %EXIT_CODE%
    pause
)
exit /b %EXIT_CODE%

:silent
"%PYEXE%" "%APP%" >>"%GUI_LOG%" 2>&1
exit /b 0