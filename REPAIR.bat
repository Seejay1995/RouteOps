@echo off
setlocal
echo Repairing RouteOps v0.5.0 in the active EDDiscovery data root...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Repair failed. Review the messages above.
  pause
  exit /b 1
)
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify.ps1"
pause
