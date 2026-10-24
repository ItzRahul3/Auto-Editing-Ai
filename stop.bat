@echo off
taskkill /FI "WINDOWTITLE eq AutoEdit Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq AutoEdit Frontend*" /T /F >nul 2>nul
echo AutoEdit AI stopped.
