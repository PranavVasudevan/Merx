<#
.SYNOPSIS
    Feature 17 (C14) — backtest harness: X-Ray, deposit-flight and filing-diff
    signals against every landed quarter transition. Publishes hit rate, lift
    and confidence intervals to ml/backtest/results.json.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.backtest_cli
