# One-time setup: create the virtual environment and install dependencies.
# Usage:  powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "AI Video Assistant - setup" -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Find a usable Python ────────────────────────────────────────────────────
# torch and chromadb publish wheels for 3.11 / 3.12. Newer versions (and alphas)
# will fail to install, so pick a supported interpreter explicitly.
$python = $null
foreach ($version in @("3.11", "3.12", "3.10")) {
    & py "-$version" --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $python = @("py", "-$version")
        Write-Host "[ok]   Using Python $version" -ForegroundColor Green
        break
    }
}

if (-not $python) {
    Write-Host "[fail] No Python 3.10-3.12 found." -ForegroundColor Red
    Write-Host "       Install Python 3.11 from https://www.python.org/downloads/release/python-3119/"
    Write-Host "       (tick 'Add python.exe to PATH' in the installer), then re-run this script."
    exit 1
}

# ── 2. Virtual environment ─────────────────────────────────────────────────────
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[..]   Creating virtual environment in .venv" -ForegroundColor Yellow
    & $python[0] $python[1] -m venv .venv
} else {
    Write-Host "[ok]   Virtual environment already exists" -ForegroundColor Green
}

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# ── 3. Dependencies ────────────────────────────────────────────────────────────
Write-Host "[..]   Upgrading pip" -ForegroundColor Yellow
& $venvPy -m pip install --upgrade pip --quiet

Write-Host "[..]   Installing PyTorch (CPU build, ~250 MB)" -ForegroundColor Yellow
& $venvPy -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    Write-Host "[warn] CPU wheel failed; falling back to the default index." -ForegroundColor Yellow
    & $venvPy -m pip install torch
}

Write-Host "[..]   Installing the remaining requirements (this takes a few minutes)" -ForegroundColor Yellow
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[fail] Dependency installation failed - see the pip output above." -ForegroundColor Red
    exit 1
}

# ── 4. .env ────────────────────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[new]  Created .env - add your MISTRAL_API_KEY to it" -ForegroundColor Yellow
} else {
    Write-Host "[ok]   .env already exists" -ForegroundColor Green
}

# ── 5. ffmpeg ──────────────────────────────────────────────────────────────────
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "[ok]   ffmpeg found on PATH" -ForegroundColor Green
} else {
    Write-Host "[fail] ffmpeg is NOT installed - the pipeline cannot run without it." -ForegroundColor Red
    Write-Host "       Install it with:  winget install Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host "       Then close this window, open a new terminal, and re-run setup.ps1."
}

Write-Host ""
& $venvPy -m app.doctor
Write-Host ""
Write-Host "Next:  .\run.ps1" -ForegroundColor Cyan
Write-Host ""
