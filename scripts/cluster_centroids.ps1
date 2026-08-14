<#
.SYNOPSIS
    Feature 14 (C3) — fit and persist fixed behavioral-cluster centroids on the
    latest landed quarter, for stable multi-quarter cluster assignment.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_ingestion.cluster_centroids_cli
