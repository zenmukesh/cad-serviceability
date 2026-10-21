@echo off
title Stop CAD Serviceability System

echo Stopping CAD Serviceability processes...

taskkill /F /IM uvicorn.exe /T 2>nul
taskkill /F /FI "WINDOWTITLE eq CAD Backend*" /T 2>nul
taskkill /F /FI "WINDOWTITLE eq CAD Frontend*" /T 2>nul

echo All services stopped.
timeout /t 2 >nul
exit
