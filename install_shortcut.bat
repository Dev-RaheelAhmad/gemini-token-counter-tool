@echo off
setlocal
pushd "%~dp0"
title Install Gemini Token Monitor Desktop Shortcut
echo Installing Gemini Token Monitor Desktop Shortcut...
powershell -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
echo.
echo Done! You can now launch "Gemini Token Monitor" directly from your Desktop.
popd
pause
