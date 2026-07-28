@echo off
title YTStar Downloader
echo ==============================================
echo        Starting YTStar Local Server
echo ==============================================
echo.

cd /d "%~dp0"

echo [*] Installing/checking Python dependencies...
pip install -r backend/requirements.txt

echo [*] Opening YTStar in your web browser...
start http://localhost:8000

echo [*] Starting FastAPI Backend server...
cd backend
python main.py

pause
