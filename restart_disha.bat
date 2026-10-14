@echo off
title Restart DISHA
cd /d "%~dp0"
echo ====================================================
echo   Stopping any existing DISHA processes...
echo ====================================================
for /f "tokens=5" %%a in ('netstat -ano ^| findstr 54321 ^| findstr LISTENING 2^>nul') do (
    echo Terminating PID %%a holding port 54321...
    taskkill /F /PID %%a >nul 2>&1
)
ping 127.0.0.1 -n 2 >nul
echo Launching clean DISHA instance...
start "" /d "%~dp0" "venv\Scripts\pythonw.exe" "main.py"
echo DISHA has been restarted!
ping 127.0.0.1 -n 2 >nul
