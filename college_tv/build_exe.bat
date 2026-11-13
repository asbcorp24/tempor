@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Build College TV EXE

echo ==========================================
echo Building College TV executable for Windows
echo ==========================================

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 goto :no_python
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :fail
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo.
echo Building executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --name CollegeTV --add-data "templates;templates" --hidden-import flask --hidden-import jinja2 --collect-all flask --collect-all werkzeug app.py
if errorlevel 1 goto :fail

if not exist "dist\CollegeTV.exe" goto :fail

echo.
echo ==========================================
echo SUCCESS: dist\CollegeTV.exe
echo ==========================================
echo Copy CollegeTV.exe to a writable folder and run it.
echo Database schedule.db will be created alongside the EXE.
echo Admin: http://localhost:5000/admin
echo TV:    http://localhost:5000/tv
pause
exit /b 0

:no_python
echo ERROR: Python 3 not found. Install Python and retry.
pause
exit /b 1

:fail
echo ERROR: Build failed. Read messages above.
pause
exit /b 1
