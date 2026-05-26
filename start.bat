@echo off
chcp 65001 >nul
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.
    pause
    exit /b 1
)

pip install -r requirements.txt -q >nul 2>&1

start "" pythonw main.py
