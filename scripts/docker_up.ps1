<#
.SYNOPSIS
    Build and run the BankLens app tier (bridge + quant terminal) in Docker.
    Needs Docker Desktop running. Mounts your local data/ read-only — land data
    first with the usual scripts (run_vertical_slice.ps1, crosswalk.ps1, etc.).
.EXAMPLE
    powershell -File scripts/docker_up.ps1
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
docker compose -f (Join-Path $repo "platform/docker/docker-compose.app.yml") up --build
