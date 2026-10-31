@echo off
rem Search Anything - one-step start for Windows. Double-click this file.
rem Uses Docker Desktop when it is running, otherwise Python (.venv).
rem Options: --docker  --no-docker  --folder D:\Work  (and app options)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
