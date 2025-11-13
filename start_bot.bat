@echo off
REM This file runs the bot in the background using pythonw.exe

REM Get the directory where this .bat file is located
SET "BATCH_DIR=%~dp0"

REM Run the bot without a console window
start "" "%BATCH_DIR%venv\Scripts\pythonw.exe" "%BATCH_DIR%bot.py"
