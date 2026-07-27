# services/agents — the "ask it anything" analyst copilot (Phase 6)

A **supervisor** routes a free-text question to the **specialist** best equipped to
answer it; the specialist chains BankLens's MCP tools (never raw data) to build an
answer. This is agents as the third consumer of the same backend the UI and CLI use.

## Three interchangeable providers — default is $0

This project has a hard **$0 spending rule**. `providers.py` picks the backend at
call time via `BANKLENS_LLM_PROVIDER` (default **`ollama`**):

| Provider | Cost | Status |
|---|---|---|
| **ollama** (default) | **$0 forever** — runs on your own machine | ✅ live-tested, real bugs found and fixed (below) |
| **gemini** | $0 with a free-tier API key | built + unit-tested; no key was available to test live |
| **anthropic** | costs money — no perpetual free tier | built + unit-tested; not run live in this environment |

All three implement the identical `messages_create(*, model, system, messages, tools,
tool_choice) -> {"content": [...], "stop_reason": ...}` shape, so `agent.py` and
`supervisor.py` don't know or care which one is under them — swapping providers is
a config change (`--provider` flag or the env var), never a code change.

## How it works

1. **Supervisor** (`supervisor.py`) — one forced tool call classifies the question
   into a persona: `risk_analyst`, `filings_analyst`, `ma_scout`, `macro_stress`.
2. **Specialist agent** (`agent.py`) — spawns the real MCP server (`mcp_client.py`,
   stdio JSON-RPC, exactly like `services/mcp-server`), gets its tool subset, and
   runs the tool-calling loop until it has a final answer or hits the turn cap.
3. Every run is saved to `data/agent_runs/<timestamp>.json` — a second audit trail
   alongside the MCP server's own per-call log.

**Zero-install throughout:** `anthropic_client.py`, `gemini_client.py`, and
`ollama_client.py` all hand-roll their HTTP calls over stdlib `urllib` — no
`anthropic` / `google-generativeai` pip packages. Same philosophy as the FDIC
connector from day one.

## Ollama (default) — how the local-model path actually works

Ollama's *native* tool-calling API (`/api/chat` + `tools=`) was tested against
`qwen2.5-coder:3b` on this machine and returned corrupted output — even a plain
"say hello" prompt with no tools came back as `"Hello@@@@@@@@..."` (a broken local
model/server state, not a code bug). `ollama_client.py` instead uses a plain-text
tool-call protocol — describe the tools in the prompt, ask for a JSON action, extract
it robustly — the same approach project-matcher already validated works for small
local models. Default model is **`llama3.2:1b`**, confirmed working cleanly here;
try `qwen2.5-coder:3b` again after `ollama pull qwen2.5-coder:3b` if you want a
sharper (if slower) model.

### Real bugs found (and fixed) by actually running this live
1. **Type coercion at the MCP boundary.** The local model sent `{"cert": "6976"}`
   (string) for an integer-typed parameter, which failed a dict lookup keyed by real
   ints with a misleading "not found" error. Fixed in `services/mcp-server`'s
   `server.py` (`_coerce_arguments`) — benefits **every** MCP client, not just weak
   local models.
2. **Duplicate-call loop.** The model reliably got the *correct* tool result, but
   didn't recognize "I have enough information, stop and answer" — it just
   re-issued the identical call until the turn cap. Fixed in `agent.py`: a repeated
   `(name, arguments)` pair is answered from cache (no wasted MCP round-trip) with an
   explicit nudge; two repeats in a row force one final `tools=None` call, which
   *guarantees* termination with a real answer.
3. **Stray tool-call artifacts as "final answers."** Even after getting real data,
   the model's "final answer" turn was sometimes itself a malformed JSON fragment
   (`{"get_bank_xray": {...}}`) rather than prose. `agent.py`'s `_finalize()` detects
   this shape and substitutes the real underlying tool data instead of showing the
   user a confusing artifact.

After all three fixes, a real live run (`llama3.2:1b`, fully local, $0) produced:
> "Dime Community Bank appears to be of high concentration risk due to a
> single-sector loan concentration with 73.8% of its book concentrated in one
> sector. Additionally, its CRE-to-equity ratio is above 300% [...] the uninsured
> deposit reliance is also elevated [...]"

— correct, coherent, and grounded entirely in the real `get_bank_xray` tool result.
**Honest limitation:** a 1B local model needed all three fixes above to get there
reliably; expect noticeably rougher edges than Gemini/Claude would give, especially
on harder multi-tool questions.

## Gemini — genuinely free, multi-key rotation (untested live, no key available)

`gemini_client.py` uses Gemini's native function-calling and `gemini_keys.py` — a
near-verbatim port of project-matcher's own key-rotation module — so a Gemini
deployment gets the same "drop in N keys, get Nx the free-tier quota" behavior.
**"1 main + 4 backups"**: set `GEMINI_API_KEY` (main) + `GEMINI_API_KEY_1`..`_4`
(backups), or `GEMINI_API_KEYS=k1,k2,k3,k4,k5`. Get free keys at
https://aistudio.google.com/apikey. On 401/403/429 the pool transparently rotates to
the next key instead of failing the run. Translation logic is unit-tested against a
mocked HTTP layer (`test_gemini_client.py`) but was never exercised against the real
API in this environment — the JSON-Schema `type` handling in particular is a
documented, unverified assumption (see `gemini_client.py`'s docstring).

## Anthropic — costs money, off by default

`anthropic_client.py` is fully built and unit-tested but was never called live in
this environment (no key available, and the project's $0 rule means it likely never
will be here). Switch to it explicitly (`--provider anthropic`) only if you decide to
spend money.

## Run it

```powershell
# default: ollama, $0, works right now
powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
powershell -File scripts/agent_ask.ps1 -Persona macro_stress "stress Dime under a severe deposit run"

# once you've set GEMINI_API_KEY* in .env:
powershell -File scripts/agent_ask.ps1 -Provider gemini "..."
```

## Tests (all hermetic — no API key, no live network, no cost)

`test_mcp_client.py` (real MCP round-trip on real data) · `test_personas.py`
(persona/tool-registry consistency) · `test_anthropic_client.py` /
`test_gemini_keys.py` (key resolution & rotation logic) · `test_gemini_client.py`
(Anthropic-shaped ⇄ Gemini wire-format translation, HTTP mocked) ·
`test_ollama_client.py` (JSON extraction robustness, tool-call parsing, safe
fallbacks) · `test_providers.py` (provider resolution, **and that the default is
verifiably `ollama`, the free one**) · `test_agent_loop.py` (the full loop against
the real MCP server, including regression tests for all three bugs above).
Run: `python services/agents/tests/test_*.py`.

`tests/run_eval.py` + `eval_questions.json` — a routing-quality regression check
(per the master plan, "agents are tested like code"). Needs a real key for the
paid/external providers; works with `ollama` (default) for $0.

## Next (beyond this reference)
A true multi-turn conversation (this is single-question); RAG over filing text
(`search_filings_text` doesn't exist yet — needs pgvector/Qdrant, Phase 2+);
tracing (OpenTelemetry); cost/latency budgets; human-in-the-loop gates for any future
side-effectful tool.
