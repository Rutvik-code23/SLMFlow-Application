<#
.SYNOPSIS
    SLMFlow Medical AI - one-command setup and start script (Windows PowerShell).

.DESCRIPTION
    1. Creates .venv if it does not exist yet
    2. Installs SLMFlow 0.1.1 from TestPyPI
    3. Installs the other Python dependencies from PyPI
    4. Installs the frontend packages and builds the UI
    5. Starts the backend, which also serves the built UI

    Then open http://127.0.0.1:8000 in your browser.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Port 9000
    .\start.ps1 -Dev        # keeps the Vite dev server instead of the build
#>
param(
    [int]$Port = 8000,
    [switch]$Dev,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step($text) {
    Write-Host ""
    Write-Host ">> $text" -ForegroundColor Cyan
}

# --------------------------------------------------------------------------- #
# 1. Python virtual environment
# --------------------------------------------------------------------------- #
Step "Python virtual environment"
$pyExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pyExe)) {
    Write-Host "   creating .venv ..."
    python -m venv .venv
} else {
    Write-Host "   .venv already exists"
}

# --------------------------------------------------------------------------- #
# 2 + 3. Python dependencies
# --------------------------------------------------------------------------- #
if ($SkipInstall) {
    Write-Host "   skipping install because -SkipInstall was passed"
} else {
    Step "Upgrading pip"
    & $pyExe -m pip install --upgrade pip --quiet

    Step "Installing SLMFlow from TestPyPI"
    # --no-deps on purpose: SLMFlow's core has zero required dependencies, and
    # TestPyPI does not host its transitive requirements.
    & $pyExe -m pip install --index-url https://test.pypi.org/simple/ --no-deps slmflow==0.1.1

    Step "Installing the other Python dependencies from PyPI"
    & $pyExe -m pip install -r requirements.txt
}

# --------------------------------------------------------------------------- #
# 4. Frontend
# --------------------------------------------------------------------------- #
$frontendDir = Join-Path $PSScriptRoot "frontend"
$distIndex = Join-Path $frontendDir "dist\index.html"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "   Node.js was not found on PATH, so the UI cannot be built." -ForegroundColor Yellow
    Write-Host "   Install it from https://nodejs.org and re-run this script."
    Write-Host "   The backend will still start and answer on /api/*."
} else {
    Step "Frontend packages"
    Push-Location $frontendDir
    try {
        if (-not (Test-Path "node_modules") -or -not $SkipInstall) {
            Write-Host "   npm install ..."
            npm install
        }
        if (-not $Dev) {
            Step "Building the frontend"
            npm run build
        }
    } finally {
        Pop-Location
    }
}

# --------------------------------------------------------------------------- #
# 5. Start the app
# --------------------------------------------------------------------------- #
Step "Starting the backend"
Write-Host "   URL: http://127.0.0.1:$Port"
Write-Host "   Press Ctrl+C to stop."
Write-Host ""

if ($Dev) {
    Write-Host "   Dev mode: the Vite dev server runs on http://127.0.0.1:5173" -ForegroundColor Yellow
    Push-Location $frontendDir
    try { npm run dev } finally { Pop-Location }
} else {
    & $pyExe -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
}
