@echo off
title Outreach Studio
cd /d "%~dp0"
echo Starting Outreach Studio. Your browser will open in a moment.
echo Keep this window open while you work. Close it when you are done.
"%~dp0venv\Scripts\python.exe" -m streamlit run app.py
pause
