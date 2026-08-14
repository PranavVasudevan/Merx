<#
.SYNOPSIS
    Feature 12 (C13) — population-level multiple-testing summary for filing_diff:
    expected false positives at the raw z threshold, plus a Benjamini-Hochberg
    FDR-controlled alternative flag set.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.filing_diff_population_cli
