@echo off
title CAD Serviceability Launcher

echo ========================================================
echo  Launching CAD Serviceability Assessment System...
echo ========================================================

:: 1. Start FastAPI Backend Server
echo [1/3] Starting Backend API (http://127.0.0.1:8000)...
start "CAD Backend (FastAPI)" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

:: 2. Start Vite React Frontend
echo [2/3] Starting Frontend Dev Server (http://127.0.0.1:5173)...
start "CAD Frontend (Vite)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

:: 3. Wait briefly for services to spin up, then open browser
echo [3/3] Waiting for servers to initialize...
timeout /t 3 /nobreak >nul

echo Opening browser at http://localhost:5173...
start http://localhost:5173

echo.
echo ========================================================
echo  Application is running!
echo  To stop the application, run 'stop_app.bat' or close
echo  the backend and frontend terminal windows.
echo ========================================================
exit
