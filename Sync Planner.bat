@echo off
title Sync outreach stats to planner
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" scripts\sync_lovable.py
pause
