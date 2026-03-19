@echo off
title WiFi Speaker
echo.
echo  ==========================================
echo   WiFi Speaker - Starting...
echo  ==========================================
echo.

py -3.11 "%~dp0wifi_speaker.py"

echo.
echo  Stream ended. Press any key to close.
pause > nul
