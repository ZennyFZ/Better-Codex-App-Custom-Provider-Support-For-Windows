@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "GUI_SCRIPT=%SCRIPT_DIR%patch_chatgpt_providers_windows_gui.py"
cd /d "%SCRIPT_DIR%"

if not exist "%GUI_SCRIPT%" (
    echo [ERROR] GUI script was not found beside this launcher.
    pause
    exit /b 1
)

where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" /wait pythonw.exe "%GUI_SCRIPT%"
    set "EXIT_CODE=%ERRORLEVEL%"
    goto :finish
)

where py.exe >nul 2>&1
if not errorlevel 1 (
    py.exe -3 "%GUI_SCRIPT%"
    set "EXIT_CODE=%ERRORLEVEL%"
    goto :finish
)

where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe "%GUI_SCRIPT%"
    set "EXIT_CODE=%ERRORLEVEL%"
    goto :finish
)

echo [ERROR] Python 3 was not found. Install Python with Tcl/Tk support first.
pause
set "EXIT_CODE=1"

:finish
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
