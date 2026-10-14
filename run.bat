@echo off
title DISHA - AI Companion
cd /d "%~dp0"
echo ====================================================
echo   Launching DISHA AI Assistant (Live Console Mode)
echo ====================================================
echo.

REM Automatically stop any previous background/stale instance holding port 54321
netstat -ano | findstr 54321 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Stopping previous background instance on port 54321...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr 54321 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    ping 127.0.0.1 -n 2 >nul
)

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe main.py
) else (
    echo [ERROR] Virtual environment not found at venv\Scripts\python.exe!
    pause
    exit /b 1
)

if %errorlevel% neq 0 (
    echo.
    echo DISHA exited with error code %errorlevel%.
    pause
)
