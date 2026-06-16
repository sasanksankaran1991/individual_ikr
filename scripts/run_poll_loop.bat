@echo off
REM Run Telegram poll + reminders in a loop (Windows). Keep this window open.
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe scripts\poll_loop.py
) else (
    python scripts\poll_loop.py
)
