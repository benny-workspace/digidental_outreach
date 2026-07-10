@echo off
title Outreach Studio
cd /d "%~dp0"

rem If a previous session was closed uncleanly, Streamlit's default port
rem (8501) can be left occupied by a stuck process. Detect that up front
rem instead of silently hanging or opening a broken connection.
netstat -ano | findstr ":8501 " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Port 8501 is already in use, probably a previous Outreach Studio
    echo session that did not close cleanly.
    echo.
    echo 1. If Outreach Studio is already open in your browser, use that
    echo    window instead of opening a new one.
    echo 2. Otherwise, close any other black "Outreach Studio" windows,
    echo    then run this shortcut again.
    echo.
    pause
    exit /b 1
)

echo Starting Outreach Studio. Your browser will open in a moment.
echo Keep this window open while you work. Close it when you are done.
"%~dp0venv\Scripts\python.exe" -m streamlit run app.py
pause
