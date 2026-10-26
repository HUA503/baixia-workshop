@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title BAIXIA - Install

where python >nul 2>nul
if errorlevel 1 (
  echo [BAIXIA] Python was not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

echo Installing Python dependencies...
if "%~1"=="" (
  python -m pip install --disable-pip-version-check -r requirements.txt
) else (
  python -m pip install --disable-pip-version-check -i "%~1" -r requirements.txt
)
if errorlevel 1 (
  echo.
  echo Installation failed. You can try a mirror:
  echo   install.bat https://pypi.tuna.tsinghua.edu.cn/simple
  pause
  exit /b 1
)
echo.
echo Done. Double-click run.bat to start BAIXIA.
pause
