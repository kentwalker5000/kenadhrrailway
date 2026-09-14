@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\native.py" start
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://localhost:8000"
