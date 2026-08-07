@echo off
rem ============================================
rem  Tokyo Metro Alert (TMA) launcher
rem  Double-click to start the server and open
rem  the app in your browser.
rem ============================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    echo Run the following once to set it up:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

start "" "http://127.0.0.1:5000/"

echo Starting Tokyo Metro Alert (TMA) ... (close this window to stop)
".venv\Scripts\python.exe" app.py

pause
