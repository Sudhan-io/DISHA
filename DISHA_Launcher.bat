@echo off
REM ====================================================================
REM DISHA Portable Launcher
REM Auto-detects its drive letter and launches DISHA in USB Mode.
REM ====================================================================

set CURRENT_DIR=%~dp0
set DRIVE=%~d0

if exist "%CURRENT_DIR%venv\Scripts\pythonw.exe" (
    set DISHA_DIR=%CURRENT_DIR:~0,-1%
) else if exist "%DRIVE%\DISHA\venv\Scripts\pythonw.exe" (
    set DISHA_DIR=%DRIVE%\DISHA
) else (
    set DISHA_DIR=%CURRENT_DIR:~0,-1%
)

set PYTHONW=%DISHA_DIR%\venv\Scripts\pythonw.exe
set MAIN=%DISHA_DIR%\main.py

if not exist "%PYTHONW%" (
    echo [ERROR] DISHA virtual environment not found!
    echo Looked at: "%PYTHONW%"
    echo Please make sure the venv folder is present in the DISHA folder.
    pause
    exit /b 1
)

cd /d "%DISHA_DIR%"

REM If running from an external portable drive (not C: or D:), enforce USB portable security
if /i not "%DRIVE%"=="C:" if /i not "%DRIVE%"=="D:" (
    set DISHA_USB_MODE=true
)

start "" "%PYTHONW%" "%MAIN%"
