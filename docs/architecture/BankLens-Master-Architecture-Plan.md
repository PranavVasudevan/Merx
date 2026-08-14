# BankLens — Master Architecture Plan

A bank-intelligence platform over the full FDIC-insured US bank population
(~4,350 banks, every size band) plus EU significant institutions (EBA
Transparency Exercise), built on real regulatory filings under a hard $0
spend constraint. This document describes the architecture as implemented —
see `docs/audit/01-current-state.md` for an independent effectiveness
scorecard and `docs/audit/03-issue-register.md` for known gaps.

## 1. Data layer — medallion architecture (Bronze / Silver / Gold)

- **Bronze** (`pipelines/ingestion`): raw, as-fetched records from each
  source, landed with per-partition provenance (`_provenance.json`: source
  URL, fetch timestamp, content checksum) and append-only history so a prior
  quarter's restated numbers are never overwritten in place.
- **Silver** (`pipelines/transforms/src/banklens_transforms/silver.py`,
  `silver_eba.py`): normalized, typed records — one schema across FDIC and
  EBA sources where the two genuinely map, with a field left `None` and the
  gap disclosed (not averaged away) where they don't.
- **Gold** (`pipelines/transforms/src/banklens_transforms/gold.py`): derived
  ratios, concentration metrics, peer percentiles and behavioral clusters,
  computed once per quarter and served from there — never recomputed
  ad hoc per request in a way that could drift between two pages.

## 2. Data sources

`config/sources.yaml` is the source registry (one entry per connector: name,
license tag, landing status). Connectors live under
`pipelines/ingestion/src/banklens_ingestion/sources/` and share one contract
(`sources/base.py`'s `Source` class: `discover -> fetch -> checksum -> land`),
implemented stdlib-only. Sources include FDIC BankFind (institution +
financial data, public domain), FDIC Summary of Deposits (branch-level,
annual), EBA Transparency Exercise (EU banks), SEC EDGAR (10-K risk-factor
text), Fed NIC (holding-company structure), FRED (macro series) and Tiingo
(market data, licensed — see `platform/auth/README.md`-adjacent licensing
notes in `config/sources.yaml` for the redistribution constraint on this one).

## 3. Serving layer

Two services read the same Gold layer and share one authorization policy
(`platform/auth/opa/policy.rego` — see `platform/auth/README.md`):

- **MCP server** (`services/mcp-server`): the tool-calling interface real
  agents (this project's own agent fleet, or any external MCP client) use.
  Each tool in `banklens_mcp.tools.TOOLS` reads Gold/feature functions and
  returns a JSON-serialisable result — see `docs/api/mcp-tools.md` for the
  full tool registry.
- **REST bridge** (`services/api-gateway`): a dependency-free HTTP wrapper
  exposing the *same* tool functions as plain REST/JSON for the frontend
  (`bridge_server.py`'s module docstring: routing, auth, error mapping and
  metrics all live in one `_route_request()` function so the dev
  (`ThreadingHTTPServer`) and prod (gunicorn/WSGI) transports can never
  serve different responses for the same request).

## 4. Frontend

`frontend/apps/web` — a React + TypeScript quant-terminal SPA (Vite build),
talking to the REST bridge via `src/api.ts`. Charting is deliberately
multi-library rather than one-size-fits-all (Recharts for standard charts,
ECharts for heatmaps/treemaps/network graphs, `lightweight-charts` for
candlesticks) with a shared contract layer (tooltip, formatter, empty/error
state conventions) so the libraries stay visually consistent.

## 5. Deployment

Designed to run on $0: the REST bridge's CORS origins, API base URL and OIDC
provider are all environment-configurable rather than hardcoded to
localhost; the Gold layer can be materialized into a single DuckDB file
under free-tier storage limits; the LLM provider auto-falls-back away from a
model server free hosts can't run (see §8); Postgres connects via a plain
`DATABASE_URL` so free hosted tiers (Neon, Supabase) work unmodified. See
`docs/audit/03-issue-register.md`'s "A" issue group for the specific gaps
this line of work closes.

## 6. Data quality discipline

`data_quality.py` and equivalents encode *disclosed* exclusions rather than
silent clamping — e.g. institutions with near-zero deposit funding
(clearing houses, custody banks) are named, with their real figures and
exclusion reason, rather than quietly dropped or winsorized. The same
discipline extends to capital-regime detection (CBLR vs risk-based vs
foreign-branch-no-capital) and to every "not computed" leg of the stress
simulator (`legs_not_applied`) — an unmeasured figure is reported as
unmeasured, never defaulted to zero and presented as a verdict.

## 7. Testing & CI

`.github/workflows/ci.yml` runs, per language: Python lint (`ruff`) +
the full stdlib-runner test suite (`scripts/run_all_tests.py`, discovering
every `test_*.py` under `pipelines/`, `services/`, `libs/`); Rust
`clippy` + `cargo test` for the stress-engine and ingestion crates; frontend
typecheck + Vitest + build; and Docker/Kustomize manifest validation. Tests
needing landed Bronze data or an optional native dependency (QuantLib) SKIP
rather than fail when absent, so CI stays honest about coverage instead of
silently going green on a handful of files.

## 8. Agent fleet — Supervisor + specialist personas

A Supervisor (`services/agents/src/banklens_agents/supervisor.py`) routes a
free-text question to the specialist persona best equipped to answer it,
rather than handing every question to one generalist agent guessing among
every MCP tool at once. Routing is a single cheap/fast LLM call with a
**forced** tool call (`tool_choice={"type": "tool", "name": "route"}`) — a
structured decision, not a parsed sentence, and identical across providers
since every client module translates the same forced-tool request into its
own wire format.

**Personas** (`personas.py`), each a system prompt plus an allowed-tool
subset:

| Persona | Focus | Key tools |
|---|---|---|
| `risk_analyst` | Concentration/run risk, deposit-flight resemblance | `get_bank_xray`, `get_risk_score`, `get_risk_leaderboard`, `get_quarterly_briefing`, `get_model_card` |
| `financial_analyst` | Profitability, credit quality, funding, capital | `get_population_metrics`, `get_metric_distribution`, `get_percentile_heatmap`, `get_asset_treemap` |
| `filings_analyst` | Quarter-over-quarter filing changes, 10-K text | `diff_filings`, `get_bank_trends`, `search_filings_text`, `get_filings_coverage` |
| `ma_scout` | Acquisition/partnership fit | `find_ma_matches`, `get_peer_cluster`, `get_cluster_diagnostics`, `get_county_concentration`, `get_branch_map`, `get_ma_network` |
| `macro_stress` | Capital resilience under stress, market context | `run_stress_test`, `run_bulk_stress_test`, `run_stress_comparison`, `get_market_snapshot`, `get_price_candles` |
| `generalist` | Fallback when routing is inconclusive | every tool above |

Every persona shares one constraint baked into its system prompt: answer
**only** by calling tools, never invent a number, and cite concrete figures
and percentiles from the tool results actually returned.

**The tool-calling loop** (`agent.py`): provider-agnostic — whichever
backend `providers.get_client()` resolves to, the loop logic is identical,
since every client module returns the same
`{"content": [...], "stop_reason": ...}` shape. Bounded to `MAX_TURNS=6`
round-trips so a confused model can't loop forever burning tokens (or, for
local Ollama inference, wall-clock). A duplicate-call guard answers a
repeated `(tool_name, arguments)` pair from cache with an explicit nudge,
and forces a final answer after two repeats — found live against a small
local model (`llama3.2:1b`) that reliably got correct tool results but
didn't reliably recognize when to stop calling tools.

**Provider selection** (`providers.py`): defaults to Ollama when explicitly
chosen (the only backend with genuinely $0 marginal cost), but auto-detects
when no provider is explicitly configured — probes Ollama with a short
timeout, and falls back to Gemini's free tier (multi-key rotation, see
`gemini_keys.py`) if Ollama isn't reachable, since a deployment on free
hosting can't run a local model server. Anthropic is **never** chosen by
auto-detection; it is the one provider that costs real money and requires an
explicit `BANKLENS_LLM_PROVIDER=anthropic` (or an explicit `provider=`
argument) to use.

**Authorization**: every tool call an agent makes still passes through the
MCP server's own per-tool OPA check (`banklens_mcp/authz.py` — see
`platform/auth/README.md`), keyed by the caller's actual roles, not the
persona's nominal tool list — a viewer-role user's session can't reach an
analyst-tier tool just because a persona's `tool_names` happens to include
it.
