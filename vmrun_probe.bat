@echo off
chcp 65001 >nul
cd /d "%~dp0"
python vmrun_probe.py
echo.
echo Result written to vmrun_probe_result.txt
pause
