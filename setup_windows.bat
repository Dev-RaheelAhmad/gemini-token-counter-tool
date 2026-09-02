@echo off
setlocal enabledelayedexpansion
title Gemini Token Monitor - Windows Setup
pushd "%~dp0"

echo ======================================================
echo       Gemini Token Monitor - Windows Installer
echo ======================================================
echo.

:: 1. Detect Python
set "PY_CMD="
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python was not found in your system PATH.
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    popd
    pause
    exit /b 1
)

echo [1/3] Checking Python environment...
%PY_CMD% --version
if %errorlevel% neq 0 (
    echo [ERROR] Failed to execute Python.
    popd
    pause
    exit /b 1
)

echo.
echo [2/3] Installing GUI dependencies (CustomTkinter, Pystray, Pillow)...
if exist "%~dp0requirements.txt" (
    %PY_CMD% -m pip install -r "%~dp0requirements.txt" --quiet --disable-pip-version-check
) else (
    %PY_CMD% -m pip install customtkinter pystray Pillow darkdetect packaging --quiet --disable-pip-version-check
)
if %errorlevel% neq 0 (
    echo [WARNING] Pip install with quiet flag returned a non-zero code. Retrying with standard install...
    if exist "%~dp0requirements.txt" (
        %PY_CMD% -m pip install -r "%~dp0requirements.txt"
    ) else (
        %PY_CMD% -m pip install customtkinter pystray Pillow darkdetect packaging
    )
)

echo.
echo [3/3] Creating Windows Desktop and Start Menu Shortcuts...
powershell -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"

echo.
echo ======================================================
echo   Installation Complete!
echo   A shortcut "Gemini Token Monitor" is on your Desktop.
echo ======================================================
echo.
echo Launching Gemini Token Monitor...
start "" "%~dp0run_gui.bat"

popd
timeout /t 3 >nul
