<#
.SYNOPSIS
    Start the BankLens REST bridge (wraps banklens_mcp.tools over HTTP for the
    quant-terminal frontend). Listens on http://localhost:8791.
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "services/mcp-server/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python (Join-Path $repo "services/api-gateway/src/bridge_server.py")
