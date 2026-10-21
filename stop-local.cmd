@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0local_control.py" stop
if errorlevel 1 pause
