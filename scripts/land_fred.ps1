<#
.SYNOPSIS
    Land FRED macro series (Treasury yield curve, Fed funds, unemployment,
    CRE price index) to Bronze. Needs the user's own free FRED_API_KEY
    (https://fred.stlouisfed.org/docs/api/api_key.html) in .env.
.EXAMPLE
    powershell -File scripts/land_fred.ps1
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.fred_land_cli
