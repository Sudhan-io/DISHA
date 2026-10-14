@echo off
title DISHA - AI Companion
cd /d "%~dp0"
echo ====================================================
echo   Launching DISHA AI Assistant (Live Console Mode)
echo ====================================================
echo.

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
