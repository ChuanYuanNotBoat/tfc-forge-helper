@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -m pip install -e ".[dev]"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m ruff check src tests scripts packaging
set "result=%errorlevel%"
pause
exit /b %result%
