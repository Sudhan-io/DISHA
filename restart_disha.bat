@echo off
title Restart DISHA
cd /d "%~dp0"
echo ====================================================
echo   Stopping existing DISHA and Ollama processes...
echo ====================================================
for /f "tokens=5" %%a in ('netstat -ano ^| findstr 54321 ^| findstr LISTENING 2^>nul') do (
    echo Terminating PID %%a holding port 54321...
    taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /IM ollama.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul

REM Set Ollama models directory and start server
if exist "D:\Ollama\models" set OLLAMA_MODELS=D:\Ollama\models
set OLLAMA_EXE=
if exist "D:\Ollama\ollama.exe" set OLLAMA_EXE=D:\Ollama\ollama.exe
if not defined OLLAMA_EXE for /f "tokens=*" %%i in ('where ollama 2^>nul') do set OLLAMA_EXE=%%i
if defined OLLAMA_EXE start "" /b "%OLLAMA_EXE%" serve

echo Launching clean DISHA instance...
start "" /d "%~dp0" "venv\Scripts\pythonw.exe" "main.py"
echo DISHA has been restarted!
ping 127.0.0.1 -n 2 >nul
