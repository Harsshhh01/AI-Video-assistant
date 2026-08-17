# Start the web server. Usage:  .\run.ps1  [-Port 8000] [-NoBrowser]
param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "No virtual environment found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

# ── Is the port already taken? ─────────────────────────────────────────────────
# Without this check uvicorn dies with a raw socket error that reads like the app
# is broken, when in fact an older copy of it is still running.
try {
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch {
    $busy = $null
}

if ($busy) {
    $pid1 = @($busy)[0].OwningProcess
    $proc = Get-Process -Id $pid1 -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Port $Port is already in use by PID $pid1 ($($proc.ProcessName))." -ForegroundColor Red
    Write-Host ""
    Write-Host "If that is an older copy of this server, stop it with:" -ForegroundColor Yellow
    Write-Host "    Stop-Process -Id $pid1 -Force"
    Write-Host "Or start this one on a different port:" -ForegroundColor Yellow
    Write-Host "    .\run.ps1 -Port 8080"
    Write-Host ""
    exit 1
}

# ── Warn about missing prerequisites, but still start ──────────────────────────
# The web UI reports these itself; this is just a heads-up in the terminal.
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "Warning: ffmpeg is not on PATH - analyses will fail." -ForegroundColor Yellow
    Write-Host "         Fix with: winget install Gyan.FFmpeg  (then open a NEW terminal)" -ForegroundColor DarkGray
}
if ((Test-Path ".env") -and -not (Select-String -Path ".env" -Pattern '^\s*MISTRAL_API_KEY\s*=\s*\S' -Quiet)) {
    Write-Host "Warning: MISTRAL_API_KEY is empty in .env - summaries and chat will fail." -ForegroundColor Yellow
}

$url = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "Starting AI Video Assistant on $url" -ForegroundColor Cyan
Write-Host "Loading Whisper and Chroma takes about 10-20 seconds on first start." -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

# ── Open the browser only once the server actually answers ─────────────────────
# Opening it immediately raced the server's startup and showed the user a
# connection-refused page, which looks like the app failed to launch.
if (-not $NoBrowser) {
    Start-Job -Name "ava-browser" -ScriptBlock {
        param($target)
        for ($i = 0; $i -lt 120; $i++) {
            try {
                Invoke-WebRequest -Uri "$target/api/health" -TimeoutSec 2 -UseBasicParsing | Out-Null
                Start-Process $target
                return
            } catch {
                Start-Sleep -Milliseconds 700
            }
        }
    } -ArgumentList $url | Out-Null
}

try {
    & $venvPy -m uvicorn app.server:app --host 127.0.0.1 --port $Port
} finally {
    Get-Job -Name "ava-browser" -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
}
