@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -r requirements-release-lock.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install --no-deps -e ".[dev,release]"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\build_release.py
set "result=%errorlevel%"
pause
exit /b %result%
