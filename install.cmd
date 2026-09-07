@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "install_status=%ERRORLEVEL%"
if not "%install_status%"=="0" pause
exit /b %install_status%
