@echo off
setlocal

cd /d "%~dp0"

chcp 65001 >nul
set "PYTHONUTF8=1"
if not defined BOT_EXCHANGE set "BOT_EXCHANGE=binance-usdm"
set "PROJECT_DIR=%~dp0"
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8765"
set "FRONTEND_URL=http://127.0.0.1:5173"
set "BACKEND_URL=http://%BACKEND_HOST%:%BACKEND_PORT%"
if not defined BOT_HISTORY_DB_PATH if exist "data\history.sqlite" set "BOT_HISTORY_DB_PATH=data\history.sqlite"

if not exist ".venv\Scripts\python.exe" (
    echo The Python virtual environment was not found.
    echo.
    echo Run these commands first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

if not exist "web\package.json" (
    echo The web dashboard folder was not found.
    echo Expected: %PROJECT_DIR%web\package.json
    echo.
    pause
    exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
    echo npm was not found. Install Node.js, then run this file again.
    echo.
    pause
    exit /b 1
)

if exist "web\node_modules" (
    set "DASHBOARD_CMD=npm.cmd run dev"
) else (
    set "DASHBOARD_CMD=call npm.cmd install && npm.cmd run dev"
)

set "BACKEND_CMD=.venv\Scripts\python.exe -m btc_trading_bot.web --exchange %BOT_EXCHANGE% --host %BACKEND_HOST% --port %BACKEND_PORT%"

echo Starting BTC Tri-Factor web stack...
echo Backend API: %BACKEND_URL%
echo Dashboard:   %FRONTEND_URL%
echo Exchange:    %BOT_EXCHANGE%
if defined BOT_HISTORY_DB_PATH echo History DB:  %BOT_HISTORY_DB_PATH%
echo.

start "BTC Tri-Factor Backend API" /D "%PROJECT_DIR%" cmd /k "%BACKEND_CMD%"
start "BTC Tri-Factor Web Dashboard" /D "%PROJECT_DIR%web" cmd /k "%DASHBOARD_CMD%"

echo.
echo Two command windows were opened. Keep both running while using the dashboard.
echo Waiting for the backend API to become ready...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(120); do { try { $response = Invoke-WebRequest -Uri '%BACKEND_URL%/api/snapshot' -UseBasicParsing -TimeoutSec 3; if ($response.StatusCode -eq 200) { exit 0 } } catch { }; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo.
    echo The backend API did not become ready at %BACKEND_URL%.
    echo Check the "BTC Tri-Factor Backend API" window for the startup error.
    echo The dashboard will show proxy errors until the backend is running.
    echo.
    pause
    exit /b 1
)

echo Backend is ready. Opening the dashboard...
start "" "%FRONTEND_URL%"

endlocal
