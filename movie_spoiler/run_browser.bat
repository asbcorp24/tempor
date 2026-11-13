@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto error
py -3 -m playwright install chromium
if errorlevel 1 goto error
py -3 browser_import.py %*
if errorlevel 1 goto error
echo.
echo Finished. Database: spoilers.db
pause
exit /b 0
:error
echo.
echo Browser importer failed. Check messages above.
pause
exit /b 1
