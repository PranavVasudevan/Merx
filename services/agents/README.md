# services/agents — the "ask it anything" analyst copilot (Phase 6)

A **supervisor** routes a free-text question to the **specialist** best equipped to
answer it; the specialist chains BankLens's MCP tools (never raw data) to build an
answer. This is agents as the third consumer of the same backend the UI and CLI use.

## How it works

1. **Supervisor** (`supervisor.py`) — one forced tool call on **Haiku** (cheap/fast)
   classifies the question into a persona: `risk_analyst`, `filings_analyst`,
   `ma_scout`, or `macro_stress`.
2. **Specialist agent** (`agent.py`) — spawns the real MCP server
   (`mcp_client.py`, stdio JSON-RPC, exactly like `services/mcp-server`), gets its
   tool subset, and runs the standard tool-calling loop on **Sonnet** (default) until
   it has a final answer or hits the turn cap.
3. Every run is saved to `data/agent_runs/<timestamp>.json` — question, persona,
   every tool call + result preview, final answer. A second audit trail alongside the
   MCP server's own per-call log.

**Zero-install, on purpose:** `anthropic_client.py` hand-rolls the Messages API over
stdlib `urllib` (no `anthropic` pip package) — the same philosophy as the FDIC
connector. It reads `ANTHROPIC_API_KEY` from the environment or `.env`.

## Run it

```powershell
# get a key from https://console.anthropic.com/settings/keys, then either:
#   set ANTHROPIC_API_KEY=sk-...          (this shell only)
#   or add ANTHROPIC_API_KEY=sk-... to .env at the repo root (already git-ignored)

powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
powershell -File scripts/agent_ask.ps1 -Persona macro_stress "stress Dime under a severe deposit run"
```

## Tested without an API key

`tests/test_mcp_client.py` (real MCP round-trip on real data), `test_personas.py`
(persona/tool-registry consistency), `test_anthropic_client.py` (key resolution),
`test_agent_loop.py` (the tool-calling loop against the real MCP server, with only
the LLM call mocked). Run: `python services/agents/tests/test_*.py`.

`tests/run_eval.py` + `eval_questions.json` — a routing-quality regression check
(per the master plan, "agents are tested like code"). Needs a real key; not part of
the hermetic suite, run manually.

## Next (beyond this reference)
A true multi-turn conversation (this is single-question); RAG over filing text
(`search_filings_text` doesn't exist yet — needs pgvector/Qdrant, Phase 2+);
tracing (OpenTelemetry); cost/latency budgets; human-in-the-loop gates for any future
side-effectful tool.
