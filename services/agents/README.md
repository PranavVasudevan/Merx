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

Five genuine **code** bugs, each caught by an actual live run and each fixed with a
regression test (not just patched and hoped):

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
3. **Stray tool-call artifacts as "final answers"** — in **two different shapes**
   caught on different runs: `{"get_bank_xray": {...}}` (tool name as the dict key)
   and `{"tool": "list_banks", "query": ..., ...}` (tool name as a `"tool"` field's
   *value*, arguments flattened to the top level). `agent.py`'s
   `_looks_like_stray_tool_call` / `_finalize()` catch both and substitute the real
   underlying tool data — or an honest "couldn't parse, try again" message if no
   real data was ever retrieved either.
4. **Non-dict JSON crashing `.items()`/`.get()`.** The model's raw output sometimes
   parsed as perfectly *valid* JSON that wasn't an object — a bare quoted string
   (`"CERT1234"`), for instance — and every caller assumed dict semantics. Fixed at
   the source: `ollama_client._extract_json` now only ever returns a dict or `None`.
5. **PowerShell parameter binding** (`agent_ask.ps1`): without explicit `Position`
   attributes, a single bare argument bound to `-Persona` (declared first) instead
   of the question text. Fixed with `[CmdletBinding(PositionalBinding = $false)]`.

After all five fixes, a real live run (`llama3.2:1b`, fully local, $0) reliably
retrieves the correct tool data and produces a coherent, mostly-accurate summary —
e.g. correctly citing Dime's real `overall_risk: "high"`, its 73.8% loan
concentration, and its CRE-to-capital ratio above 300%, all lifted straight from
the real `get_bank_xray` result.

### Where code fixes stop and model capability begins — two distinct failure modes, not one

**1. Orchestration failures (fixed by the 5 bugs above).** Whether the loop calls
the right tool, with valid arguments, and terminates — this is now solid.

**2. Synthesis inaccuracy (not fixable by more code).** Even when the *tool-calling*
is fully correct, the model's *prose summary* of a correct result can still contain
a specific, confidently-stated wrong claim. Caught live on the very same "how risky
is Dime" question that worked well above: on a separate run, the model additionally
claimed "the CET1 ratio is relatively low, indicating a relatively leveraged bank" —
which is **wrong**; Dime's real CET1 is 14.6%, a strong position, and CET1 wasn't
even one of the 3 flags the X-Ray raised. No amount of JSON-parsing robustness
touches this — it's the model's language-generation step misstating a number it had
correct access to, not a broken tool call.

**3. Full hallucination on harder questions.** An open-ended question ("which banks
look most exposed to a deposit run *right now*?" — no cert given) went further: the
model invented a fake certificate number and fabricated an answer citing "Wells
Fargo"/"Bank of America" with numbers matching no real tool result at all (every
actual tool call it made errored). It skipped the necessary first step — look up
real candidates — and confabulated instead.

**Net assessment:** treat Ollama's output as "a decent first-pass narrative that
usually gets tool-calling and the big picture right, but verify any specific number
against the saved tool-result JSON (`data/agent_runs/*.json`) before trusting it" —
not as a fully reliable analyst. This is the honest ceiling of a free, local,
1B-parameter model. For better synthesis quality at the same $0 cost, configure
Gemini; for the best quality, Anthropic (costs money).

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
