@echo off
rem Double-click to start VocalCut Studio (see scripts\start.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 pause
