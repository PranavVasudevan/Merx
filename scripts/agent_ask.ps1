<#
.SYNOPSIS
    Ask the BankLens agent fleet a question — the supervisor routes it to a
    specialist, which chains MCP tools to answer. Requires ANTHROPIC_API_KEY
    (set in .env or the environment).
.EXAMPLE
    powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
    powershell -File scripts/agent_ask.ps1 -Persona macro_stress "stress-test Dime Community Bank under a severe deposit run"
#>
param(
    [string]$Persona = "",
    [string]$Model = "sonnet",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Question
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "services/agents/src") + ";" + (Join-Path $repo "services/mcp-server/src") + ";" + (Join-Path $repo "pipelines/transforms/src")

$opt = @("--model", $Model)
if ($Persona) { $opt += @("--persona", $Persona) }
python -m banklens_agents.cli @opt @Question
