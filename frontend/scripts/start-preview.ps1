param([ValidateRange(1, 65535)][int]$Port = 3002, [switch]$FrontendOnly)

$ErrorActionPreference = 'Stop'
$previewRoot = Split-Path -Parent $PSScriptRoot
$previewUrl = "http://127.0.0.1:$Port/paper-trading"
$previewListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$previewLogs = Join-Path $previewRoot 'node_modules/.cache/local-preview'
New-Item -ItemType Directory -Path $previewLogs -Force | Out-Null

if (-not $FrontendOnly) {
    $previewBackendRoot = Join-Path (Split-Path -Parent $previewRoot) 'backend'
    $previewPython = Join-Path $previewBackendRoot '.venv/Scripts/python.exe'
    $previewBackendListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if (-not $previewBackendListener) {
        if (-not (Test-Path -LiteralPath $previewPython)) {
            throw 'Existing backend environment missing. Set up backend/.venv or use -FrontendOnly for fixture pages.'
        }
        $previewBackendProcess = Start-Process -FilePath $previewPython `
            -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
            -WorkingDirectory $previewBackendRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $previewLogs 'backend-stdout.log') `
            -RedirectStandardError (Join-Path $previewLogs 'backend-stderr.log') -PassThru
        $previewBackendProcess.Id | Set-Content -LiteralPath (Join-Path $previewLogs 'backend-pid.txt')
    }
    $previewBackendReady = $false
    for ($previewBackendAttempt = 0; $previewBackendAttempt -lt 30; $previewBackendAttempt++) {
        try {
            $previewHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
            if ($previewHealth.status -eq 'ok') { $previewBackendReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $previewBackendReady) { throw 'Backend did not become healthy. Check node_modules/.cache/local-preview/backend-stderr.log.' }
    Write-Output 'Dashboard backend ready: http://127.0.0.1:8000'
}

if (-not $previewListener) {
    if (-not (Test-Path -LiteralPath (Join-Path $previewRoot '.next/BUILD_ID'))) {
        throw 'Production build missing. Run npm run build in frontend first.'
    }
    $previewNode = (Get-Command node -ErrorAction Stop).Source
    # Detached hidden process survives the agent's temporary command session.
    $previewProcess = Start-Process -FilePath $previewNode `
        -ArgumentList @('node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', "$Port") `
        -WorkingDirectory $previewRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $previewLogs 'stdout.log') `
        -RedirectStandardError (Join-Path $previewLogs 'stderr.log') -PassThru
    $previewProcess.Id | Set-Content -LiteralPath (Join-Path $previewLogs 'pid.txt')
}

for ($previewAttempt = 0; $previewAttempt -lt 15; $previewAttempt++) {
    try {
        $previewResponse = Invoke-WebRequest -Uri $previewUrl -TimeoutSec 2
        if ($previewResponse.StatusCode -eq 200 -and $previewResponse.Content.Contains('Paper Trading')) {
            Write-Output "Preview ready: $previewUrl"
            return
        }
    } catch {
        if ($previewAttempt -eq 14) { throw }
    }
    Start-Sleep -Seconds 1
}
throw 'The port did not return the Paper Trading page. Existing services were not stopped.'
