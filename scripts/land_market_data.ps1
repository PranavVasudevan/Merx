<#
.SYNOPSIS
    Land real EOD price history (Tiingo) for banks the crosswalk matched to a real
    ticker. Requires TIINGO_API_KEY (free, no card — get one at
    https://api.tiingo.com/account/api/token). Needs scripts/crosswalk.ps1 run first.
.EXAMPLE
    powershell -File scripts/land_market_data.ps1
    powershell -File scripts/land_market_data.ps1 -Limit 50
#>
param(
    [int]$Limit = 20,
    [int]$RefreshDays = 1,
    [string]$StartDate = "2023-01-01"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.market_cli --limit $Limit --refresh-days $RefreshDays --start-date $StartDate
