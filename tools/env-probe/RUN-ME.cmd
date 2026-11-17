@echo off
rem VSE Toolbox environment probe launcher (read-only, no admin needed)
chcp 65001 >nul
title VSE Toolbox environment probe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0vse_env_probe.ps1" %*
if errorlevel 1 (
  echo.
  echo [!] PowerShell did not finish. Please take a screenshot of this window and send it back.
)
echo.
pause
