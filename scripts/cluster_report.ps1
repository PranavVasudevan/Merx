<#
.SYNOPSIS
    Feature 14 — recluster the peer set by behavior and show the size-label mismatch.
.EXAMPLE
    powershell -File scripts/cluster_report.ps1
    powershell -File scripts/cluster_report.ps1 -HighlightCert 3511 -K 5
#>
param(
    [string]$Repdte = "20260331",
    [int]$HighlightCert = 6976,
    [int]$K = 0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
$kArg = if ($K -gt 0) { @("--k", $K) } else { @() }
python -m banklens_ingestion.clustering_cli --repdte $Repdte --highlight-cert $HighlightCert @kArg
