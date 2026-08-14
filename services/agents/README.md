# `banklens_agents`

The agent fleet: a Supervisor that routes a free-text question to the
specialist persona best equipped to answer it, each reasoning over a
focused MCP tool subset instead of guessing among every tool at once. Full
architecture writeup: `docs/architecture/BankLens-Master-Architecture-Plan.md`
§8.

## Running it

```
python -m banklens_agents.cli "which banks look most exposed to a deposit run?"
python -m banklens_agents.cli --persona macro_stress "stress Dime under a 60% run"
python -m banklens_agents.cli --provider gemini "..."     # once GEMINI_API_KEY* is set
python -m banklens_agents.cli --provider anthropic "..."  # costs money — off by default
```

Default provider is **Ollama** (`BANKLENS_LLM_PROVIDER` overrides) — this
project has a hard $0 spending rule, and Ollama is the only backend that
costs nothing to actually run. See `providers.py` for the auto-detection
fallback to Gemini's free tier when Ollama isn't reachable (used by the
bridge's `/api/assistant/ask` when no provider is explicitly configured, so
a free-tier deployment without a local model server still works). Anthropic
is never chosen automatically — using it always requires an explicit
`--provider anthropic` / `BANKLENS_LLM_PROVIDER=anthropic`.

## Persistence

Every run is saved to `data/agent_runs/<timestamp>.json` (the full
transcript: question, persona, every tool call and result, final answer) AND
indexed in the real `agent_runs` Postgres table (see
`libs/python/banklens_common/src/banklens_common/db.py`) so it's queryable
without grepping flat files — the same store the MCP server's own audit log
uses. If Postgres is unreachable the JSON transcript still gets written; see
`docs/runbooks/disaster-recovery.md` for the fail-open behaviour and its
limits.

## Package layout

| Module | Role |
|---|---|
| `supervisor.py` | Routes a question to a persona via a single forced-tool-call LLM request |
| `personas.py` | System prompt + allowed-tool subset per specialist (`risk_analyst`, `financial_analyst`, `filings_analyst`, `ma_scout`, `macro_stress`, `generalist`) |
| `agent.py` | The provider-agnostic tool-calling loop: question → LLM → MCP tool calls → answer, bounded to `MAX_TURNS=6` |
| `providers.py` | Picks which backend's `messages_create` the loop/supervisor call, with auto-detection when unset |
| `anthropic_client.py` / `gemini_client.py` / `ollama_client.py` | One thin client per provider, all returning the same `{"content": [...], "stop_reason": ...}` shape |
| `gemini_keys.py` | Multi-key rotation for Gemini's free tier |
| `mcp_client.py` | Stdio client the agent loop uses to actually call the MCP server's tools |
| `cli.py` | The interactive entry point shown above |

Every tool call an agent makes is still evaluated by the MCP server's own
per-tool OPA check (`services/mcp-server/src/banklens_mcp/authz.py`) against
the caller's real roles — a persona's `tool_names` is a hint for what the
model should try, not a bypass of authorization.
