<#
.SYNOPSIS
    Run the FULL BankLens test suite (all 23 files, 135 tests) with zero
    dependencies — each test file has a built-in stdlib runner, so pytest is
    optional. This is the same entry point CI uses.

    Tests that need landed Bronze data (`data/`, git-ignored and reproducible via
    the landing scripts) SKIP rather than fail when it's absent, so this is safe
    on a fresh clone.
.EXAMPLE
    powershell -File scripts/run_tests.ps1
    powershell -File scripts/run_tests.ps1 -Quiet
#>
param([switch]$Quiet)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$opt = @()
if ($Quiet) { $opt += "--quiet" }
python (Join-Path $repo "scripts/run_all_tests.py") @opt
