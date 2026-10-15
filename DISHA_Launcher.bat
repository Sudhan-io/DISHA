@echo off
REM ====================================================================
REM DISHA Launcher
REM Auto-starts Ollama local AI server and DISHA, and cleanly stops
REM Ollama when the DISHA task ends.
REM ====================================================================
title DISHA AI Assistant Launcher
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0
set DRIVE=%~d0

echo ====================================================
echo          DISHA AI Assistant Launcher
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
        echo [WARN] Ollama executable not found. Offline local LLM will be disabled.
    )
) else (
    echo [INFO] Ollama is already active on port 11434.
)

REM 4. Check for virtual environment python
set PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe
if not exist "%PYTHON%" (
    echo [ERROR] Virtual environment not found at: "%PYTHON%"
    echo Please make sure the venv folder exists in %SCRIPT_DIR%
    pause
    exit /b 1
)

REM 5. Clean up any previous dead/zombie DISHA instances on port 54321
netstat -ano | findstr 54321 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Cleaning up previous DISHA session on port 54321...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr 54321 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 1 /nobreak >nul
)

REM 6. Run DISHA (runs until you close DISHA or this task)
echo.
echo [INFO] Launching DISHA AI Assistant...
echo [INFO] Keep this window open while using DISHA, or close it to stop DISHA and Ollama.
echo.
"%PYTHON%" "%SCRIPT_DIR%main.py"

REM 7. When DISHA task ends, automatically shut down Ollama
echo.
echo ====================================================
echo   DISHA ended. Stopping Ollama server...
echo ====================================================
taskkill /F /IM ollama.exe >nul 2>&1
echo [OK] Ollama stopped cleanly.
timeout /t 1 /nobreak >nul
exit /b 0
