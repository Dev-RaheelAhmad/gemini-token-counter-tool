@echo off
setlocal
pushd "%~dp0"

:: Check for pythonw in PATH
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0token_counter_gui.pyw"
    popd
    exit /b 0
)

:: Check for python in PATH
where python >nul 2>nul
if %errorlevel% equ 0 (
    start "" python "%~dp0token_counter_gui.pyw"
    popd
    exit /b 0
)

:: Check py launcher
where py >nul 2>nul
if %errorlevel% equ 0 (
    start "" py -3 "%~dp0token_counter_gui.pyw"
    popd
    exit /b 0
)

echo [ERROR] Python not found. Please install Python from python.org.
popd
pause
