<#
.SYNOPSIS
    Feature 14 (C10) — validate whether X-Ray severity predicts subsequent
    equity underperformance, using landed Tiingo price data. Needs
    scripts/land_market_data.ps1 to have landed price history first.
#>
param([int]$HorizonDays = 63)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" `
    + (Join-Path $repo "pipelines/transforms/src") + ";" `
    + (Join-Path $repo "services/mcp-server/src") + ";" `
    + (Join-Path $repo "libs/python/banklens_common/src")
python -m banklens_ingestion.xray_validation_cli --horizon-days $HorizonDays
