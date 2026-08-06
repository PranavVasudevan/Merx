<#
.SYNOPSIS
    Land the EBA EU-wide Transparency Exercise (~120 significant EU/EEA banks'
    balance sheet, capital, P&L) to Bronze. Keyless — no API key needed.
.EXAMPLE
    powershell -File scripts/land_eba.ps1
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.eba_land_cli
