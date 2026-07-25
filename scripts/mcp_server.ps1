<#
.SYNOPSIS
    Launch the BankLens MCP server (stdio). Normally an MCP client launches this;
    run it directly only to sanity-check startup (Ctrl+C to stop).
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "services/mcp-server/src") + ";" + (Join-Path $repo "pipelines/transforms/src")
python -m banklens_mcp.server
