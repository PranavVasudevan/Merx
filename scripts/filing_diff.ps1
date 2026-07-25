<#
.SYNOPSIS
    Feature 12 — diff a bank's filings between two quarters, flagging moves that are
    unusual vs the bank's own history.
.EXAMPLE
    powershell -File scripts/filing_diff.ps1 -Cert 6976
    powershell -File scripts/filing_diff.ps1 -Cert 3511 -QuarterA 2024Q4 -QuarterB 2026Q1
#>
param(
    [int]$Cert = 6976,
    [string]$QuarterA = "",
    [string]$QuarterB = "",
    [double]$ZThreshold = 2.0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
$opt = @("--cert", $Cert, "--z-threshold", $ZThreshold)
if ($QuarterA) { $opt += @("--quarter-a", $QuarterA) }
if ($QuarterB) { $opt += @("--quarter-b", $QuarterB) }
python -m banklens_ingestion.filing_diff_cli @opt
