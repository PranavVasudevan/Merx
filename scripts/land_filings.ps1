<#
.SYNOPSIS
    Feature 17 (Tier 6 capstone) — land + extract + embed real SEC 10-K Item 1A
    risk-factor text for population banks with a confident CERT<->CIK crosswalk
    match. B8 (docs/audit/04-remediation-prompts.md): resumes from a persisted
    cursor over the FULL eligible universe, round-robin across runs, rather than
    always re-landing the same head — re-run this periodically to keep growing
    coverage. Needs Ollama running locally with nomic-embed-text pulled, and the
    Postgres/pgvector container up (platform/docker/docker-compose.dev.yml).
.EXAMPLE
    powershell -File scripts/land_filings.ps1
    powershell -File scripts/land_filings.ps1 -Limit 100
#>
param([int]$Limit = 40, [int]$RefreshDays = 180)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" `
    + (Join-Path $repo "pipelines/transforms/src") + ";" `
    + (Join-Path $repo "libs/python/banklens_common/src")
python -m banklens_ingestion.filings_cli --limit $Limit --refresh-days $RefreshDays
