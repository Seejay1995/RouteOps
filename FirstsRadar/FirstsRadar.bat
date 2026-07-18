@echo off
rem RouteOps Firsts Radar launcher -- opens the colour-coded window with no console.
cd /d "%~dp0"
start "" pythonw firsts_radar.py
if errorlevel 1 start "" python firsts_radar.py
