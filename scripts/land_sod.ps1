<#
.SYNOPSIS
    Land the FDIC Summary of Deposits (branch-level footprint, ~76k records/year)
    to Bronze. Keyless — unlike Tiingo, no API key needed. Feeds Feature 15's
    real geographic-overlap upgrade.
.EXAMPLE
    powershell -File scripts/land_sod.ps1
#>
param([int]$Year = 2025)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.sod_cli --year $Year
