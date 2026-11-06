@echo off
REM Registers the sync daemon in Windows Task Scheduler, like the bot's create_tasks.bat
REM (bot starts 09:15; the daemon starts 09:10 so it is already running when the feed writes).
REM Run once, from an Administrator prompt. Remove with: schtasks /delete /tn "CloudSync_Daemon" /f
net session >nul 2>&1
if not %errorLevel% == 0 (
    echo This script requires administrator privileges. Right-click, "Run as administrator".
    exit /b 1
)
set PROJECT_DIR=%~dp0..
schtasks /create /tn "CloudSync_Daemon" /tr "\"%PROJECT_DIR%\scripts\start_sync_daemon.bat\"" /sc daily /st 09:10 /ru "%USERNAME%" /f
schtasks /query /tn "CloudSync_Daemon"
