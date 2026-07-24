@echo off
setlocal
cd /d "%~dp0"
title Indicator Lab Launcher
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_indicator_lab.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Indicator Lab could not start. Details:
  if exist "%~dp0launcher.log" type "%~dp0launcher.log"
  echo.
  pause
)
exit /b %EXIT_CODE%
