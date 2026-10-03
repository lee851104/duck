@echo off
setlocal
cd /d "%~dp0"
set "LINE_EXPORT_FX=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319"
if not exist "%LINE_EXPORT_FX%\csc.exe" set "LINE_EXPORT_FX=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319"
if not exist "bin" mkdir "bin"
"%LINE_EXPORT_FX%\csc.exe" /nologo /target:winexe /platform:anycpu /codepage:65001 /main:LineExportMonitor.ExportProgram /out:"bin\LineExportMonitor.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:"%LINE_EXPORT_FX%\WPF\UIAutomationClient.dll" /reference:"%LINE_EXPORT_FX%\WPF\UIAutomationTypes.dll" /reference:"%LINE_EXPORT_FX%\WPF\WindowsBase.dll" "OcrMonitor.cs" "ExportDelta.cs" "ExportAutomation.cs" "ExportMonitor.cs" "ExportTests.cs"
exit /b %errorlevel%
