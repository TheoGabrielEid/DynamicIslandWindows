@echo off
setlocal
cd /d "%~dp0"

rem Find a Python that really works. "python" on its own can be the Microsoft
rem Store shortcut, which only prints "Python was not found", so every
rem candidate is test-run before it is used. The "py" launcher goes first.
set "PY="
for %%C in (py python python3) do (
    if not defined PY (
        %%C -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul && set "PY=%%C"
    )
)
if not defined PY (
    echo.
    echo  Python 3.9 or newer was not found.
    echo  Install it from https://www.python.org/downloads/ and run this file again.
    echo.
    pause
    exit /b 1
)

rem Install the required packages the first time
%PY% -c "import PyQt6, psutil, pycaw, comtypes, winrt.windows.media.control, numpy, soundcard" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages, please wait...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  Could not install the required packages. Check the messages above.
        echo.
        pause
        exit /b 1
    )
)

rem Start with pythonw so no console window stays open behind the island
set "PYW="
for /f "delims=" %%P in ('%PY% -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"') do set "PYW=%%P"
if exist "%PYW%" (
    start "" "%PYW%" "%~dp0dynamic_island.py"
    exit /b 0
)

%PY% dynamic_island.py
if errorlevel 1 (
    echo.
    echo  Dynamic Island closed unexpectedly.
    echo  Details: %APPDATA%\DynamicIsland\crash.log
    echo.
    pause
)
