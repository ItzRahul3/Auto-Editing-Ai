@echo off
cd /d "%~dp0"
if not exist .venv (echo Run install.bat first. & exit /b 1)
echo Starting AutoEdit AI (all processing stays on this computer)...
start "AutoEdit Backend" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "AutoEdit Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo Open:  http://127.0.0.1:3000
echo API docs: http://127.0.0.1:8000/docs
timeout /t 8 >nul
start http://127.0.0.1:3000
