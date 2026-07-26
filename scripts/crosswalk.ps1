<#
.SYNOPSIS
    Build the CERT<->CIK<->RSSD identity crosswalk over the landed population and
    SEC ticker directory (requires both already landed to Bronze).
.EXAMPLE
    powershell -File scripts/crosswalk.ps1
    powershell -File scripts/crosswalk.ps1 -Verify ZIONS   # live cross-source check
#>
param([string]$Verify = "")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "pipelines/ingestion/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
$opt = @()
if ($Verify) { $opt += @("--verify", $Verify) }
python -m banklens_ingestion.crosswalk_cli @opt
