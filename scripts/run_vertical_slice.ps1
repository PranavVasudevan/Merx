<#
.SYNOPSIS
    Phase-1 vertical slice: pull one real bank from FDIC and run it through
    Bronze -> Silver -> Gold. No pip installs required (stdlib only).

.EXAMPLE
    powershell -File scripts/run_vertical_slice.ps1
    powershell -File scripts/run_vertical_slice.ps1 -Cert 628 -Quarters 8
#>
param(
    [int]$Cert = 3511,       # 3511 = Wells Fargo Bank NA; 628 = JPMorgan Chase; 3510 = Bank of America
    [int]$Quarters = 6
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")

Write-Host "Running BankLens vertical slice (CERT $Cert, $Quarters quarters)..." -ForegroundColor Cyan
python -m banklens_ingestion.cli --cert $Cert --quarters $Quarters
