@echo off
title US Economy KPI Dashboard

cd /d "%~dp0"

echo ============================================================
echo   US Economy KPI Dashboard -- Recession Risk Monitor
echo ============================================================
echo.

REM Check that .env exists
if not exist ".env" (
    echo ERROR: .env file not found.
    echo.
    echo Please copy .env.example to .env and fill in your FRED_API_KEY.
    echo See SETUP_GUIDE.md for instructions.
    echo.
    pause
    exit /b 1
)

REM Check that Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Check that Flask is installed
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo Flask is not installed. Installing dependencies now...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: pip install failed. See messages above.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed successfully.
    echo.
)

echo *** IMPORTANT: Do NOT close this window. The server runs here. ***
echo.
echo If this is your first launch, the app will download 5 years of
echo historical data first (takes 2-5 minutes). Please be patient.
echo Your browser will open automatically when it is ready.
echo.

REM Open browser after a longer delay to allow bootstrap to finish (runs in background)
start "" cmd /c "timeout /t 120 /nobreak >nul && start http://localhost:5000"

echo Starting server...
echo.

python app.py

REM If we get here, app.py exited (error or Ctrl+C)
echo.
echo Dashboard stopped.
pause
