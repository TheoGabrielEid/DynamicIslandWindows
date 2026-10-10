@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" pythonw "%~dp0dynamic_island.py"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        start "" python "%~dp0dynamic_island.py"
    ) else (
        echo Python was not found in your system PATH.
        echo Please install Python 3.10+ from python.org and check 'Add python.exe to PATH'.
        pause
    )
)
exit
