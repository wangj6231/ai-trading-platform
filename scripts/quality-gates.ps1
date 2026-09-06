$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$BackendRoot = Join-Path $RepositoryRoot "backend"
$FrontendRoot = Join-Path $RepositoryRoot "frontend"
$BackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $BackendPython)) {
    throw "Backend virtual environment is missing: $BackendPython"
}

Push-Location $BackendRoot
try {
    Invoke-Checked { & $BackendPython -m ruff check app tests } "Backend Ruff"
    Invoke-Checked { & $BackendPython -m mypy app } "Backend mypy"
    Invoke-Checked {
        & $BackendPython -m pytest --cov=app --cov-report=term-missing
    } "Backend coverage"
}
finally {
    Pop-Location
}

Push-Location $FrontendRoot
try {
    Invoke-Checked { npm run quality } "Frontend quality"
}
finally {
    Pop-Location
}
