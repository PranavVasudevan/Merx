<#
.SYNOPSIS
    Run the Phase-1 test suites with zero dependencies (each test file has a
    built-in stdlib runner, so pytest is optional).
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

Write-Host "== transforms: Gold metric tests ==" -ForegroundColor Cyan
python (Join-Path $repo "pipelines/transforms/tests/test_gold_metrics.py")

Write-Host "`n== ingestion: FDIC connector tests ==" -ForegroundColor Cyan
python (Join-Path $repo "pipelines/ingestion/tests/test_fdic.py")
