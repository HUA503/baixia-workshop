@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title BAIXIA

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [BAIXIA] Python was not found. Install Python 3.10 or newer,
  echo          and check "Add Python to PATH" during installation.
  echo.
  if not defined BAIXIA_HIDDEN pause
  exit /b 1
)

python -c "import fastapi, uvicorn, multipart, PIL, fitz, docx, openpyxl, imageio_ffmpeg, cv2, numpy, onnxruntime, rapidocr_onnxruntime, pillow_heif, faster_whisper, qrcode" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [BAIXIA] First run: installing dependencies. Keep the network connected...
  python -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [BAIXIA] Installation failed. Check the network or read README.md.
    if not defined BAIXIA_HIDDEN pause
    exit /b 1
  )
)

python app.py
if errorlevel 1 if not defined BAIXIA_HIDDEN pause
