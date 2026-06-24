@echo off
setlocal

cd /d "%~dp0"

chcp 65001 >nul
set "PYTHONUTF8=1"
set "BOT_EXCHANGE=binance-usdm"
set "PROJECT_DIR=%~dp0"

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

where npm >nul 2>nul
if errorlevel 1 (
    echo npm was not found. Install Node.js, then run this file again.
    echo.
    pause
    exit /b 1
)

if exist "web\node_modules" (
    set "DASHBOARD_CMD=npm run dev"
) else (
    set "DASHBOARD_CMD=npm install && npm run dev"
)

echo Starting BTC Tri-Factor web stack...
echo Backend API: http://127.0.0.1:8765
echo Dashboard:   http://127.0.0.1:5173
echo Exchange:    %BOT_EXCHANGE%
echo.

start "BTC Tri-Factor Backend API" /D "%PROJECT_DIR%" cmd /k ".venv\Scripts\python.exe -m btc_trading_bot.web"
start "BTC Tri-Factor Web Dashboard" /D "%PROJECT_DIR%web" cmd /k "%DASHBOARD_CMD%"

echo.
echo Two command windows were opened. Keep both running while using the dashboard.
echo Opening the dashboard in your browser shortly...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173"

endlocal
