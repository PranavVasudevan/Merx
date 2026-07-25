<#
.SYNOPSIS
    Launch the BankLens quant terminal for local dev: the REST bridge (background
    window) + the Vite dev server (this window). Ctrl+C stops the dev server; close
    the bridge window separately when done.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Write-Host "Starting REST bridge (new window) on http://localhost:8791 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-File", (Join-Path $repo "scripts/api_bridge.ps1")

Start-Sleep -Seconds 2
Write-Host "Starting Vite dev server on http://localhost:5173 ..." -ForegroundColor Cyan
Push-Location (Join-Path $repo "frontend/apps/web")
try { npm run dev } finally { Pop-Location }
