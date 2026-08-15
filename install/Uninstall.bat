@echo off
setlocal
title Remove the shortcuts
cd /d "%~dp0.."

powershell -NoProfile -ExecutionPolicy Bypass -File "install\Uninstall.ps1"
pause
