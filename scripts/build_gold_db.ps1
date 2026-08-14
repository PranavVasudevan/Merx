<#
.SYNOPSIS
    Materialize the Gold layer (+footprints/county/crosswalk/clusters) into
    one queryable DuckDB artifact, for free-hosting deployments that can't
    mount the ~96MB data/bronze/ directory (see docs/audit/04-remediation-
    prompts.md, A5). Point BANKLENS_GOLD_DB at the output file to make the
    bridge/MCP server read from it instead of Bronze JSON.
.EXAMPLE
    powershell -File scripts/build_gold_db.ps1
    powershell -File scripts/build_gold_db.ps1 -Out data/banklens_gold.duckdb
#>
param(
    [string]$Out = "data/banklens_gold.duckdb"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "services/mcp-server/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_transforms.gold_db_cli --out $Out
