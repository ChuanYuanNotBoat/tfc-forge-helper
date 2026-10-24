@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    python -m venv .venv
    if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -c "import tfc_forge_helper, psutil, cv2, mss, PIL, numpy; from importlib.metadata import version; assert version('tfc-forge-helper') == tfc_forge_helper.__version__" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -e .
    if errorlevel 1 goto :failed
)
start "" ".venv\Scripts\pythonw.exe" -m tfc_forge_helper gui
exit /b 0
:failed
echo Setup failed. Install Python 3.11+ with Tk support and try again.
pause
exit /b 1
