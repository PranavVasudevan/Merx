<#
.SYNOPSIS
    Land the FDIC population slice (all US banks $1B-$250B) to Bronze, one request
    per quarter. Keyless — no API key needed. This is the peer set every percentile,
    cluster and leaderboard is computed against.

    Landing several quarters is what makes QoQ/YoY real for the whole population
    (today's single cross-section leaves every qoq_* field null) and what lets
    filing-diff work for more than the handful of individually-landed banks.
.EXAMPLE
    powershell -File scripts/land_population.ps1
    powershell -File scripts/land_population.ps1 -Quarters 8
    powershell -File scripts/land_population.ps1 -Repdte 20251231 -Quarters 4
#>
param([string]$Repdte = "20260331", [int]$Quarters = 1)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.population_land_cli --repdte $Repdte --quarters $Quarters
