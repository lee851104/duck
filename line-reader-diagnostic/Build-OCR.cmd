@echo off
setlocal
cd /d "%~dp0"
set "LINE_OCR_FX=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319"
if not exist "%LINE_OCR_FX%\csc.exe" set "LINE_OCR_FX=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319"
if not exist "bin" mkdir "bin"
"%LINE_OCR_FX%\csc.exe" /nologo /target:winexe /platform:anycpu /codepage:65001 /out:"bin\LineOcrMonitor.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "OcrMonitor.cs"
exit /b %errorlevel%
