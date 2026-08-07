@echo off
title TOYOCHO ALERT Ver2
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Setup required.
    pause
    exit /b 1
)

rem ---- stop old server on port 8100 ----
for /f "tokens=5" %%p in ('netstat -ano -p TCP ^| findstr /C:":8100 " ^| findstr /C:"LISTENING"') do taskkill /PID %%p /F >nul 2>&1

rem ---- load Web Push keys if present (optional) ----
if exist ".vapid_keys.txt" (
    for /f "usebackq tokens=1,* delims==" %%a in (".vapid_keys.txt") do set "%%a=%%b"
    echo [INFO] Web Push keys loaded.
) else (
    echo [INFO] No .vapid_keys.txt - OS notification is OFF. Screen alarm works.
)

rem ---- open browser after server boots ----
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8100"

echo.
echo  TOYOCHO ALERT Ver2  -  http://localhost:8100
echo  Close this window to stop the server.
echo.
.venv\Scripts\python.exe -m uvicorn toyocho.api:app --host 0.0.0.0 --port 8100
