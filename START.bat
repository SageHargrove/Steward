@echo off
setlocal
title Steward
cd /d "%~dp0ui"

echo.
echo   Steward
echo   =======
echo.
echo   This is the only file you need to run. Everything else, including
echo   starting and restarting the bot, is a button on the page.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   Python is not installed, or Windows cannot find it.
  echo.
  echo   Install it from https://www.python.org/downloads/ and make sure you
  echo   tick "Add python.exe to PATH" on the first screen of the installer.
  echo   Then run this file again.
  echo.
  pause
  exit /b 1
)

echo   Checking the bits it needs...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo   Could not install what it needs. The reason is printed above.
  echo   A proxy, antivirus, or no internet connection are the usual causes.
  echo.
  pause
  exit /b 1
)

echo   Done.
echo.
echo   ------------------------------------------------------------------
echo    KEEP THIS WINDOW OPEN while you use the setup page in your browser.
echo    Your bot token lives in this window's memory and nowhere else, so
echo    closing it forgets the token. Nothing already built is affected.
echo   ------------------------------------------------------------------
echo.

python app.py

echo.
echo   The setup program has stopped. You can close this window.
pause
