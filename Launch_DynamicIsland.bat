@echo off
cd /d "%~dp0"
if exist "dynamic_island.py" (
    start "" pythonw "dynamic_island.py"
) else (
    start "" pythonw "c:\Users\theog\OneDrive\Desktop\Coding Projects\DynamicIslandWindows\dynamic_island.py"
)
exit
