<#
.SYNOPSIS
    Feature 15 (C9) — validate ma_fit.DEFAULT_WEIGHTS against real deal
    history (FDIC failures' BIDNAME acquirer field) and persist the result.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.ma_weights_cli
