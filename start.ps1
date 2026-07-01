# Simple launcher for Market Research PoC (pwsh)
# Usage: .\start.ps1 [cli args...]

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path ".venv")) {
    Write-Host "Creating venv..."
    python -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"

if (-not (Test-Path ".venv\Lib\site-packages\openai")) {
    Write-Host "Installing requirements..."
    pip install -r requirements.txt
}

# Forward any args to the module (e.g. research "Company")
python -m market_research.cli $args
