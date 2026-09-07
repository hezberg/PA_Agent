@echo off
REM ============================================================
REM  PA Agent Launcher (WebUI)
REM  Project : Price Action AI Analysis Agent
REM  Usage   : Double-click this file to start the server and
REM            open the UI in your default browser.
REM  Location: C:\PA_Agent\start_pa_agent.bat
REM ============================================================
title PA Agent

cd /d D:\cl\PA_Agent
echo ============================================================
echo  Starting PA Agent (Price Action AI Analysis WebUI)...
echo  Project dir: D:\cl\PA_Agent
echo  A browser window will open at http://127.0.0.1:8765
echo ============================================================
echo.

REM Use Python 3.13 (requires-python>=3.11). py launcher picks 3.13.
py -3.13 run.py

echo.
echo ============================================================
echo  PA Agent server has exited.
echo  If the page did not load, check:
echo    C:\PA_Agent\logs\pa_agent.log
echo    C:\PA_Agent\logs\crash.log
echo ============================================================
pause
