<#
.SYNOPSIS
    Feature 15 — rank M&A partner candidates for a target bank across the peer set.
.EXAMPLE
    powershell -File scripts/ma_fit.ps1 -TargetCert 6976 -TopN 8
#>
param(
    [string]$Repdte = "20260331",
    [int]$TargetCert = 6976,
    [int]$TopN = 8
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.ma_fit_cli --repdte $Repdte --target-cert $TargetCert --top-n $TopN
