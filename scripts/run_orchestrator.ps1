<#
.SYNOPSIS
    Run the quarterly BankLens refresh DAG: land_population -> crosswalk ->
    {market_data, filings} -> {clustering, deposit_flight_retrain}, with retries
    and a durable run log at data/orchestration_runs/quarterly_refresh.jsonl.

    For real scheduling (not just an interactive run), register this as a
    Windows Task Scheduler task or `cron` job a few weeks after each quarter-end
    (FDIC call reports land ~30-45 days after quarter close) — see
    pipelines/orchestration/README.md for exact entries.
.EXAMPLE
    powershell -File scripts/run_orchestrator.ps1
    powershell -File scripts/run_orchestrator.ps1 -Repdte 20260630 -LandSod -SodYear 2026
#>
param(
    [string]$Repdte = "20260331",
    [int]$Quarters = 1,
    [switch]$LandSod,
    [int]$SodYear = 2025,
    [int]$FilingsLimit = 100,
    [int]$MarketLimit = 200
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/orchestration/src") + ";" `
    + (Join-Path $repo "pipelines/ingestion/src") + ";" `
    + (Join-Path $repo "pipelines/transforms/src")

$argsList = @("--repdte", $Repdte, "--quarters", $Quarters,
              "--filings-limit", $FilingsLimit, "--market-limit", $MarketLimit)
if ($LandSod) { $argsList += @("--land-sod", "--sod-year", $SodYear) }

python -m banklens_orchestration.quarterly_refresh @argsList
