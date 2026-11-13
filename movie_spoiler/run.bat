@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto error
py -3 movie_spoiler_scraper.py %*
if errorlevel 1 goto error
echo.
echo Finished. Database: spoilers.db
pause
exit /b 0
:error
echo.
echo An error occurred. Check Python installation and network access.
pause
exit /b 1
