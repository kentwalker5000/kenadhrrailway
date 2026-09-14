@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\native.py" stop
if errorlevel 1 (
  pause
  exit /b 1
)
