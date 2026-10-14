@echo off
REM ====================================================================
REM DISHA Launcher
REM Auto-detects drive letter, checks running status, and launches cleanly.
REM ====================================================================
title DISHA AI Assistant Launcher
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0
set DRIVE=%~d0

set PYTHONW=%SCRIPT_DIR%venv\Scripts\pythonw.exe
set PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe
set MAIN=%SCRIPT_DIR%main.py

if not exist "%PYTHONW%" (
    if exist "%PYTHON%" (
        set PYTHONW=%PYTHON%
    ) else (
        echo [ERROR] DISHA virtual environment not found!
        echo Looked at: "%PYTHONW%"
        echo Please ensure the venv folder is installed in the DISHA directory.
        pause
        exit /b 1
    )
)

REM If running from an external portable drive (not C: or D:), enforce USB portable security
if /i not "%DRIVE%"=="C:" if /i not "%DRIVE%"=="D:" (
    set DISHA_USB_MODE=true
)

REM Check if DISHA is already running
netstat -ano | findstr 54321 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] DISHA is already active!
    echo Bringing window to front...
    "%PYTHON%" -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', 54321)); s.sendall(b'ACTIVATE\n'); s.close()" >nul 2>&1
    exit /b 0
)

echo Starting DISHA AI Assistant...
start "" /d "%SCRIPT_DIR%" "%PYTHONW%" "%MAIN%"
