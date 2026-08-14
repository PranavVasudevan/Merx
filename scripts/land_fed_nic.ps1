<#
.SYNOPSIS
    Land Federal Reserve NIC holding-company data (active bank holding companies,
    open/controlling ownership relationships, one quarter of FR Y-9C financials)
    to Bronze. Keyless — no API key needed.
.EXAMPLE
    powershell -File scripts/land_fed_nic.ps1
    powershell -File scripts/land_fed_nic.ps1 -Period 20250930
#>
param([string]$Period = "20251231")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.fed_nic_land_cli --period $Period
