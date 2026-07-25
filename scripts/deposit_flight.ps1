<#
.SYNOPSIS
    Feature 13 — train the deposit-flight model on the 2022Q4 cross-section and
    validate it against the real 2023 bank failures (incl. leave-one-out).
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.deposit_flight_cli
