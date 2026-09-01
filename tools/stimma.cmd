@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stimma.ps1" %*
exit /b %ERRORLEVEL%
