@echo off
setlocal
cd /d "%~dp0"
echo === AutoEdit AI installer (Created by Rahul) ===
set MISSING=0

where python >nul 2>nul || (echo [MISSING] Python 3.11 - install from python.org and tick "Add to PATH" & set MISSING=1)
where node >nul 2>nul || (echo [MISSING] Node.js 18+ - install the LTS from nodejs.org & set MISSING=1)
where ffmpeg >nul 2>nul || (echo [MISSING] FFmpeg - see README "Install FFmpeg" & set MISSING=1)
where ffprobe >nul 2>nul || (echo [MISSING] FFprobe - it ships with FFmpeg; add its bin folder to PATH & set MISSING=1)
if "%MISSING%"=="1" (echo. & echo Fix the items above, open a NEW terminal, and run install.bat again. & exit /b 1)

python --version
node --version
python -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3,10),(3,11),(3,12)] else 1)" || (echo [WARN] Python 3.11 is recommended. Other versions may fail to install dependencies.)

if not exist .venv (echo Creating Python virtual environment... & python -m venv .venv || exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo [ERROR] pip install failed. See README troubleshooting. & exit /b 1)

echo Installing frontend packages...
pushd frontend
call npm install || (echo [ERROR] npm install failed. & popd & exit /b 1)
popd

for %%D in (models projects media\uploads media\outputs media\temp media\thumbs) do if not exist %%D mkdir %%D
if not exist .env copy .env.example .env >nul

echo.
echo Install finished. No AI models were downloaded.
echo Next: run start.bat, then open Model Manager to pick a Whisper model.
echo Bengali subtitles need a Bengali font; Windows "Nirmala UI" works (see README).
endlocal
