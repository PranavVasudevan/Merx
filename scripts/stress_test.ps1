<#
.SYNOPSIS
    Feature 16 — stress-test a bank's real balance sheet under shocks.
.EXAMPLE
    powershell -File scripts/stress_test.ps1 -Cert 3511 -LoanLoss 4 -Outflow 25 -RateBps 250
#>
param(
    [int]$Cert = 3511,
    [double]$LoanLoss = 3.0,
    [double]$Outflow = 15.0,
    [double]$RateBps = 200.0
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.stress_cli --cert $Cert --loan-loss $LoanLoss --outflow $Outflow --rate-bps $RateBps
