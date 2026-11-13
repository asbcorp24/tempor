@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title College TV - Schedule Server

if not exist "app.py" (
  echo ERROR: app.py not found. Place this BAT next to app.py.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    python -m venv .venv
    if errorlevel 1 goto :error
  )
)

if not exist ".venv\.deps_installed" (
  echo Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
  type nul > ".venv\.deps_installed"
)

echo.
echo Admin: http://localhost:5000/admin
echo TV:    http://localhost:5000/tv
echo For another device use this PC's IP address instead of localhost.
echo Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Failed to start. Make sure Python 3 is installed and added to PATH.
pause
exit /b 1
