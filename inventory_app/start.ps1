param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$pythonPath = Join-Path $appRoot '.venv/Scripts/python.exe'
$appUrl = 'http://127.0.0.1:8765'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. See README.md for setup.'
}
$running = $false
try {
    $response = Invoke-RestMethod -Uri ($appUrl + '/api/session') -TimeoutSec 2
    $running = $null -ne $response.csrf
} catch { }
if (-not $running) {
    $logDirectory = Join-Path $appRoot 'data'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Start-Process -FilePath $pythonPath -ArgumentList 'run.py' -WorkingDirectory $appRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'server.log') -RedirectStandardError (Join-Path $logDirectory 'error.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 300
        try {
            $response = Invoke-RestMethod -Uri ($appUrl + '/api/session') -TimeoutSec 1
            if ($null -ne $response.csrf) { $running = $true; break }
        } catch { }
    }
}
if (-not $running) { throw 'Unable to start. See data/error.log.' }
if (-not $NoBrowser) { Start-Process $appUrl }
