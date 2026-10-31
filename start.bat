@echo off
rem Search Anything - one-step start for Windows. Double-click this file.
rem Extra options are passed to the app, e.g.  start.bat --folder D:\Work
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
