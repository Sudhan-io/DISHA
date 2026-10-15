@echo off
title DISHA - AI Companion
cd /d "%~dp0"
echo ====================================================
echo   Launching DISHA AI Assistant (Live Console Mode)
echo ====================================================
echo.

REM 1. Set Ollama models directory
if exist "D:\Ollama\models" (
    set OLLAMA_MODELS=D:\Ollama\models
)

REM 2. Detect Ollama executable
set OLLAMA_EXE=
if exist "D:\Ollama\ollama.exe" set OLLAMA_EXE=D:\Ollama\ollama.exe
if not defined OLLAMA_EXE for /f "tokens=*" %%i in ('where ollama 2^>nul') do set OLLAMA_EXE=%%i
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe
if not defined OLLAMA_EXE if exist "%ProgramFiles%\Ollama\ollama.exe" set OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe

REM 3. Start Ollama in background if not already running
netstat -ano | findstr 11434 | findstr LISTENING >nul 2>&1
if %errorlevel% neq 0 (
    if defined OLLAMA_EXE (
        echo [INFO] Starting Ollama local AI server...
        start "" /b "%OLLAMA_EXE%" serve
        timeout /t 2 /nobreak >nul
    ) else (
        echo [WARN] Ollama executable not found.
    )
) else (
    echo [INFO] Ollama is active on port 11434.
)

REM 4. Automatically stop any previous background/stale instance holding port 54321
netstat -ano | findstr 54321 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Stopping previous background instance on port 54321...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr 54321 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    ping 127.0.0.1 -n 2 >nul
)

REM 5. Run DISHA
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe main.py
) else (
    echo [ERROR] Virtual environment not found at venv\Scripts\python.exe!
    pause
    exit /b 1
)

REM 6. When DISHA task ends, stop Ollama
echo.
echo ====================================================
echo   DISHA ended. Stopping Ollama server...
echo ====================================================
taskkill /F /IM ollama.exe >nul 2>&1
echo [OK] Ollama stopped cleanly.
timeout /t 1 /nobreak >nul
