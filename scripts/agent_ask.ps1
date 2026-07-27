<#
.SYNOPSIS
    Ask the BankLens agent fleet a question — the supervisor routes it to a
    specialist, which chains MCP tools to answer. Default provider is Ollama
    ($0, local, works with no setup). Gemini needs a free API key; Anthropic
    costs money and is off by default — see services/agents/README.md.
.EXAMPLE
    powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
    powershell -File scripts/agent_ask.ps1 -Persona macro_stress "stress-test Dime Community Bank under a severe deposit run"
    powershell -File scripts/agent_ask.ps1 -Provider gemini "..."   # once GEMINI_API_KEY* is set
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Persona = "",
    [string]$Provider = "",
    [string]$Model = "",
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Question
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = (Join-Path $repo "services/agents/src") + ";" + (Join-Path $repo "services/mcp-server/src") + ";" + (Join-Path $repo "pipelines/transforms/src")

$opt = @()
if ($Persona) { $opt += @("--persona", $Persona) }
if ($Provider) { $opt += @("--provider", $Provider) }
if ($Model) { $opt += @("--model", $Model) }
python -m banklens_agents.cli @opt @Question
