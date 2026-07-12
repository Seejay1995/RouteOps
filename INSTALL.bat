@echo off
setlocal
echo Installing EDD RouteOps v0.5.0 into the active EDDiscovery data root...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. Review the messages above.
  pause
  exit /b 1
)
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify.ps1"
pause
