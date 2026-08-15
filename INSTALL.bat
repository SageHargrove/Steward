@echo off
setlocal
title Add to the Start Menu
cd /d "%~dp0"

REM PowerShell refuses unsigned scripts by default. -ExecutionPolicy Bypass
REM applies to this one invocation only and changes nothing on the machine,
REM which is why this wrapper exists rather than telling anyone to run
REM Set-ExecutionPolicy.
powershell -NoProfile -ExecutionPolicy Bypass -File "install\Install.ps1"

if errorlevel 1 (
  echo.
  echo   Something went wrong. The reason is printed above.
  echo.
)
pause
