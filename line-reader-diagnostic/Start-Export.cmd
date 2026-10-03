@echo off
setlocal
cd /d "%~dp0"
call Build-Export.cmd
if errorlevel 1 (
  echo Build failed. Close the export tool before rebuilding.
  pause
  exit /b 1
)
start "" "bin\LineExportMonitor.exe"
