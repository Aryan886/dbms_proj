@echo off
REM Starts the cloudsync daemon next to the bot (same mechanism as the bot's start_live_data.bat).
REM Reads PG_DSN and SYNC_SQLITE from .env. Logs go to logs\sync_daemon.log.
REM The daemon backs off by itself while Postgres/RDS is unreachable; stop it with Ctrl+C or taskkill.
cd /d "%~dp0.."
if not exist logs mkdir logs
set SQLITE_PATH=data\trading_bot.db
for /f "usebackq tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="SYNC_SQLITE" set SQLITE_PATH=%%b
echo Starting cloudsync daemon on %SQLITE_PATH% ...
".venv\Scripts\python.exe" -m cloudsync sync daemon --sqlite "%SQLITE_PATH%" >> logs\sync_daemon.log 2>&1
