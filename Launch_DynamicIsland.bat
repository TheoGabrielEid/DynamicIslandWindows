@echo off
cd /d "%~dp0"
python dynamic_island.py
if errorlevel 1 (
    echo.
    echo ========================================================
    echo  Dynamic Island closed unexpectedly.
    echo  Please ensure dependencies are installed:
    echo    pip install -r requirements.txt
    echo ========================================================
    pause
)

