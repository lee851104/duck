@echo off
setlocal
cd /d "%~dp0"
call Build-OCR.cmd
if errorlevel 1 (
  echo Build failed. Close the OCR tool before rebuilding.
  pause
  exit /b 1
)
start "" "bin\LineOcrMonitor.exe"
