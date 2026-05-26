@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.12 or add python.exe to PATH, then run this file again.
    pause
    exit /b 1
)

echo Starting VM Sync from source...
echo Project: %cd%
echo.

python main.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo.
    echo VM Sync exited with error code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
