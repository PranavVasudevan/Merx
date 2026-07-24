<#
.SYNOPSIS
    Build the MVP peer set from landed Bronze and print a peer report:
    slice distribution, leaderboards, and one bank's standing vs peers.

.EXAMPLE
    powershell -File scripts/population_report.ps1
    powershell -File scripts/population_report.ps1 -HighlightCert 3511
#>
param(
    [string]$Repdte = "20260331",
    [int]$HighlightCert = 6976
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.population --repdte $Repdte --highlight-cert $HighlightCert
