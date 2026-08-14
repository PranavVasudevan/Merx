# Changelog

No version tags exist yet (pre-GA, `main` only — see `SECURITY.md`). This log is
derived from real commit history (`git log --oneline`) and the phase numbers the
code itself claims in comments/docstrings (`pyproject.toml` descriptions,
`SECURITY.md`, module docstrings) — not an invented numbering scheme. Where a
claim couldn't be independently re-verified against a specific commit, that's
said explicitly rather than presented as confirmed fact.

## Phase 9 — Real auth (OIDC + OPA), and hardening

- **Real authentication + authorization for the REST bridge**: every route
  except `/api/health`/`/metrics` now requires a signed OIDC JWT (Keycloak by
  default, any standards-compliant provider via `OIDC_ISSUER`) plus a real OPA
  policy decision (`platform/auth/opa/policy.rego`) — see
  `platform/auth/README.md`. Fails **closed**: an unreachable OIDC provider or
  OPA rejects the request (503) rather than silently allowing it through,
  verified live by stopping the `opa` container mid-session (`SECURITY.md`).
- **Per-tool authorization for the MCP server** (`services/mcp-server/src/
  banklens_mcp/authz.py`): closes the gap where any process able to spawn the
  MCP server previously got every tool with no check — evaluated against the
  same policy file the bridge uses, with an in-process tier mirror as a
  fallback only when OPA itself is unreachable.
- **Rust ports of the stress engine and an ingestion connector**
  (`services/stress-engine`, `services/ingestion`) exist in the repo, with
  `clippy` + `cargo test` (including proptest property tests for the stress
  engine) running in `.github/workflows/ci.yml`'s `rust` job. `stress.py`'s
  own docstring states the Rust port was verified byte-for-byte against the
  Python reference locally before landing; that verification predates this
  changelog and isn't independently re-confirmed here — treat it as a
  documented claim from the code itself, not a claim this entry newly
  establishes.
- `7db1840` — remediation of vulnerabilities found in a security pass:
  a path-traversal bug in `bank_quarters(cert)` (a non-numeric `CERT` could
  escape `data/` entirely — confirmed live with a planted sentinel file) and
  an `Access-Control-Allow-Origin: *` CORS misconfiguration that made the
  traversal bug reachable from any webpage a user had open. See
  `SECURITY.md`'s "Findings from an actual security pass (Phase 8)" section.

## Deployability and scheduling

- `dd0afe3` — closed EU stress-test/X-Ray coverage gaps (EBA banks were
  under-assessed relative to US banks); registered the quarterly refresh as a
  real Kubernetes CronJob (`platform/k8s/base/refresh-cronjob.yaml`,
  `0 6 5 2,5,8,11 *`) rather than leaving scheduling undocumented — see
  `pipelines/orchestration/README.md`.
- `bbb9c53`, `2ef1e1a`, `087d894` — containerized the app tier, added a real
  Kubernetes manifest, and confirmed a real Docker build/run end to end
  (including baking the trained deposit-flight model card into the bridge
  image).
- `afebace` — closed a verified path-traversal bug, tightened CORS, added the
  first version of the disaster-recovery runbook this document's own history
  traces back to (`docs/runbooks/disaster-recovery.md`).

## Data, model and analytics work

- `f7325cb` — widened sourcing (population coverage, additional connectors).
- `758e890` — surfaced previously-hidden derived features: geo overlap, full
  peer percentiles, branch footprint, richer compare/screener/leaderboard
  views.
- `aefc256` — multi-quarter population layer with stable cluster IDs, real
  quarter-over-quarter comparison, and filing-diff across the whole
  population.
- `4519f4f` — added income-statement, asset-quality and funding Gold fields;
  fixed the loan taxonomy to disjoint leaves and recalibrated the X-Ray rule
  set (91% of banks flagged "high" down to a real 27%).
- `bf4a696` — scoped the deposit-flight model and capital rules to the
  institutions they actually apply to, eliminating 208 false CET1 flags and
  raising the leave-one-out AUC from 0.938 to 0.955.
- `30845d6` — switched branch-level geography to FDIC's real per-branch
  fields instead of an invented coordinate grid, so market definitions match
  what the Fed/DOJ actually use for merger review — see
  `docs/data-contracts/branch_footprint.md`.
- `d7e6f1f` — pooled the deposit-flight training set across the 2008 and
  2023 crises; found IndyMac's honest blind spot in the earlier single-era
  model and a real off-by-one sentinel bug.
- `8135a87` — real Tiingo market-data connector, candlestick chart, two new
  MCP tools.
- `b86b5d3` — multi-provider agent backend (Ollama default, Gemini
  multi-key rotation), fixing 3 real bugs found in the process.
- `da301d9` — CERT↔CIK↔RSSD crosswalk plus a real SEC EDGAR connector, with a
  false-positive-match fix.
- `606b289` — the agent fleet: a Supervisor routing to 4 specialist personas
  over MCP (see `docs/architecture/BankLens-Master-Architecture-Plan.md` §8).
- `675871e`, `a96adab` — the deposit-flight ML model completing all 6
  planned features, and the MCP server exposing them as governed,
  audited tools.
- `a2dcfe8`/`f41d756`, `98ab78c`, `c4277be`, `6efdd8d`, `44b714d` — the
  original MVP core: bank-relative z-score filing-diff, the capital-buffer
  stress simulator (the SVB mechanism), behavioral peer clustering
  (K-Means, silhouette-selected k), the first peer-percentile/X-Ray pass,
  and the initial verified FDIC field mapping.

## Frontend

- `2decbc7` — reworked visualisations across multiple pages.
- `6e23128` — `/filings`: pgvector RAG search over real SEC 10-K risk-factor
  text.
- `8ca2359` — `/network` M&A force graph and `/stress-lab`'s cross-bank +
  QuantLib pricing-engine comparison.
- `8522ed2` — `/geography` and `/market-share`: a hand-rolled Albers branch
  map and real county-level deposit HHI.
- `d4d12a9` — `/clusters` and `/model` governance pages: silhouette-by-k
  evidence and a leave-one-out backtest with a driver beeswarm.
- `0ed3f47` — `/trends`, `/briefing`, `/filing-diff` with real side-by-side
  quarter comparison.
- `1711d27` — earnings/credit/funding/heatmap/treemap/distributions pages
  over the real `population-metrics` tools.
- `31b6e79` — split routes and vendor bundles (a 1015 kB single chunk down
  to an 84 kB entry point); added the ECharts wrapper and the first
  route/OPA-policy drift test (the direct predecessor of
  `services/api-gateway/tests/test_route_policy.py`).
- `4a4ee99`, `789abe4` — frontend restructuring and a full rebuild.
- `b973b99` — the original quant-terminal UI: a real-data dashboard over all
  6 planned features.

## Earliest history

- `3a49f48` — initial commit.
