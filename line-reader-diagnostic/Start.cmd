@echo off
setlocal
cd /d "%~dp0"
set "LINE_DIAG_FX=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319"
if not exist "%LINE_DIAG_FX%\csc.exe" set "LINE_DIAG_FX=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319"
if not exist "%LINE_DIAG_FX%\csc.exe" (
  echo Windows .NET Framework compiler was not found.
  pause
  exit /b 1
)
if not exist "bin" mkdir "bin"
"%LINE_DIAG_FX%\csc.exe" /nologo /target:winexe /platform:anycpu /codepage:65001 /out:"bin\LineReaderDiagnostic-v2.1.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:Accessibility.dll /reference:"%LINE_DIAG_FX%\WPF\UIAutomationClient.dll" /reference:"%LINE_DIAG_FX%\WPF\UIAutomationTypes.dll" /reference:"%LINE_DIAG_FX%\WPF\WindowsBase.dll" "Program.cs" "MsaaReader.cs"
if errorlevel 1 (
  echo Build failed. Close the diagnostic window before starting again.
  pause
  exit /b 1
)
start "" "bin\LineReaderDiagnostic-v2.1.exe"
