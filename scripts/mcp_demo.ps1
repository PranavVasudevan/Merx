<#
.SYNOPSIS
    Drive the BankLens MCP server over stdio and print the exchange (real MCP calls).
#>
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
python (Join-Path $repo "scripts/mcp_demo.py")
