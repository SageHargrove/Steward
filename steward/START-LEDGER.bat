@echo off
setlocal
title Steward - activity ledger
cd /d "%~dp0"

echo.
echo   Steward, the activity ledger
echo   ============================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   Python is not installed, or Windows cannot find it.
  echo   Install it from https://www.python.org/downloads/ and tick
  echo   "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b 1
)

echo   Checking the bits it needs...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo   Could not install what it needs. The reason is printed above.
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo.
  echo   ------------------------------------------------------------------
  echo    A settings file has been created for you: steward\.env
  echo.
  echo    Open it and paste your bot token after DISCORD_TOKEN=
  echo    It is the same token the setup tool used. If you no longer have
  echo    it, get a new one from the Developer Portal: your app, Bot,
  echo    Reset Token. Resetting invalidates the old one, which is fine.
  echo.
  echo    The file is ignored by git and never leaves this machine.
  echo   ------------------------------------------------------------------
  echo.
  notepad .env
)

findstr /b /c:"DISCORD_TOKEN=" .env | findstr /v /c:"DISCORD_TOKEN=" >nul 2>&1
findstr /r /c:"^DISCORD_TOKEN=." .env >nul
if errorlevel 1 (
  echo   No token in steward\.env yet. Open it, paste the token after
  echo   DISCORD_TOKEN= , save, and run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo   ------------------------------------------------------------------
echo    KEEP THIS WINDOW OPEN. The ledger only records while it runs, and
echo    Discord does not let anyone recover activity from when it was off.
echo   ------------------------------------------------------------------
echo.

python bot.py

echo.
echo   The ledger has stopped. Nothing is being recorded now.
pause
