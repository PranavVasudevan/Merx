# BankLens

BankLens is a bank intelligence platform built on public regulatory filings from
the United States and the European Union. A single data pipeline turns raw
filings into a consistent set of derived metrics, which then powers six
analyst-grade features, a governed tool interface for AI agents, and a web
dashboard. Every number in the application traces back to a real, publicly
available source — there is no sample or synthetic data anywhere in the stack.

## What it does

Given a bank's public filings, BankLens answers six concrete analyst questions:

1. **Balance-Sheet X-Ray** — does this bank have hidden concentration risk that
   its headline capital ratio doesn't show?
2. **Filing Diff** — what changed materially between two reporting quarters,
   judged against the bank's own historical volatility?
3. **Deposit-Flight Early Warning** — how closely does this bank's structure
   resemble real historical bank failures (SVB, Signature, First Republic,
   IndyMac)?
4. **Peer Group Redefiner** — which banks does this one actually behave like,
   based on loan and funding mix rather than asset size alone?
5. **M&A Fit Finder** — given a target bank, which other banks are the
   best-fit acquisition or merger partners?
6. **Capital Buffer Simulator** — what happens to this bank's capital ratios
   under a chosen loan-loss, deposit-outflow, or interest-rate shock?

A seventh capability, full-text search over real SEC 10-K risk-factor
disclosures using retrieval-augmented generation, was added as a capstone
extension.

## Data sources

| Source | Coverage | Cadence |
|---|---|---|
| FDIC BankFind Suite | ~4,500 US FDIC-insured banks — balance sheet, capital, income statement | Quarterly |
| FDIC Summary of Deposits | ~76,000 US bank branches — location and deposit totals | Annual |
| SEC EDGAR | Ticker/CIK directory and XBRL company facts, used for identity matching | Continuous |
| EBA EU-wide Transparency Exercise | ~120 significant EU/EEA banks — balance sheet, capital, income statement | Semiannual |
| European Central Bank reference rate | EUR/USD conversion, so EU and US figures are comparable | Daily |
| Tiingo | End-of-day equity prices for publicly traded banks | Daily |

All connectors call official REST APIs or official bulk-data downloads directly;
none of them scrape rendered HTML. Every fetch is logged with its source URL,
timestamp, and a content checksum for auditability. See `config/sources.yaml`
for the full source registry, including license terms.

## Architecture

Data moves through three layers, a pattern commonly called a medallion
architecture:

- **Bronze** — the raw response from each source, stored exactly as received
  and never edited. Append-only, so any number can be traced back to its
  original bytes.
- **Silver** — one normalized record per bank per quarter, with a consistent
  schema regardless of whether the bank is American or European, units
  corrected, and missing values represented explicitly rather than defaulted.
- **Gold** — derived metrics computed once and reused everywhere: financial
  ratios, quarter-over-quarter deltas, three-year growth rates, peer
  percentile ranks, and behavioral cluster assignments.

Every feature, every MCP tool, and every page in the frontend reads only from
the Gold layer. No feature re-derives a number a different way than any other
consumer of the platform.

## Tech stack

| Layer | Technology |
|---|---|
| Data connectors | Python standard library only, no third-party dependencies |
| Pipeline transforms | Pure Python, tested against real landed data |
| Statistical models | Hand-implemented logistic regression and K-means, kept intentionally simple and auditable given how little labeled data exists for bank failures |
| Stress-test math | Deterministic Python, with a QuantLib-based bond-repricing variant and a verified Rust port |
| Agent protocol | Model Context Protocol (MCP), implemented directly over JSON-RPC/stdio |
| Web API | A lightweight Python HTTP bridge exposing the same tool functions over REST |
| Databases | PostgreSQL with pgvector for filing-text search and audit logging; DuckDB for ad hoc analytical queries |
| Authentication | Keycloak for identity, Open Policy Agent for authorization |
| Frontend | React, TypeScript, Vite |
| Charting | Recharts, Apache ECharts, Lightweight Charts, and a hand-implemented Canvas map projection for branch geography |
| Deployment | Docker Compose for local development; Kustomize-based Kubernetes manifests with dev/staging/prod overlays |
| Observability | Prometheus and Grafana |
| CI | GitHub Actions — Python, Rust, and frontend build/lint checks on every change |

## Repository layout

```
banklens/
├── config/          Environment configuration and the data-source registry
├── pipelines/
│   ├── ingestion/     Bronze-layer connectors (FDIC, SEC, EBA, ECB, Tiingo)
│   ├── transforms/    Silver and Gold layer derivations
│   ├── orchestration/ Dependency-graph job runner for scheduled refreshes
│   └── dbt/           Reserved for a future SQL-based transform layer
├── services/
│   ├── mcp-server/     The MCP tool surface — 46 tools over the Gold layer
│   ├── api-gateway/     REST bridge, authentication, and routing
│   ├── agents/          The AI agent fleet (supervisor and specialist personas)
│   ├── stress-engine/   Verified Rust port of the capital-buffer simulator
│   └── ingestion/       Rust connector implementation
├── ml/              Trained model artifacts (the deposit-flight risk model)
├── frontend/        The React/TypeScript web dashboard
├── libs/            Shared Python utilities (database access, embeddings)
├── platform/        Docker, Kubernetes, authentication, and observability configuration
├── schemas/         Cross-language data contracts
├── scripts/         PowerShell entry points for every workflow below
└── data/            Landed Bronze/Silver/Gold data (not tracked in git)
```

## Getting started

The pipeline connectors require only Python 3.11 or later; no external
dependencies are needed to land data.

```powershell
# Land one bank end-to-end: fetch, Bronze, Silver, Gold
powershell -File scripts/run_vertical_slice.ps1

# Land the full US analytical population and the EU population
powershell -File scripts/land_population.ps1
powershell -File scripts/land_eba.ps1

# Re-run the same landing + Silver/Gold refresh the Kubernetes CronJob runs
# on a schedule (see below) — on demand, locally
powershell -File scripts/run_orchestrator.ps1

# Run an individual feature against a landed bank
powershell -File scripts/filing_diff.ps1 -Cert 3511
powershell -File scripts/stress_test.ps1 -Cert 6976 -Outflow 60 -RateBps 400
powershell -File scripts/deposit_flight.ps1
powershell -File scripts/ma_fit.ps1 -TargetCert 6976

# Start the MCP server, or drive it through a demo client
powershell -File scripts/mcp_server.ps1
powershell -File scripts/mcp_demo.ps1

# Start the REST bridge and the web dashboard together
powershell -File scripts/dev_web.ps1

# Run the AI agent assistant against a free-form question
powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"

# Container and cluster deployment
powershell -File scripts/docker_up.ps1
powershell -File scripts/k8s_dev_up.ps1
```

Landing market price data requires a free Tiingo API key; every other source
is keyless. Data refreshes are scheduled automatically in the Kubernetes
deployment: `platform/k8s/base/refresh-cronjob.yaml` runs the orchestration
job runner (`pipelines/orchestration/`) at 06:00 UTC on the 5th of February,
May, August and November — roughly 30–45 days after each quarter-end, which
is when US Call Reports become available (EU/EBA data refreshes only
semiannually; the DAG re-lands it every quarterly run regardless, which is
harmless and keeps one schedule instead of two). A bare local run (no
Kubernetes) has no scheduler of its own — `scripts/run_orchestrator.ps1`
above runs the same job runner on demand; register that with cron or
Windows Task Scheduler yourself to match the CronJob's cadence outside
Kubernetes.

## Data and licensing

Government sources (FDIC, SEC, EBA, ECB) are public and safe to redistribute.
Tiingo market data is commercially licensed and is registered as
non-redistributable in the source registry. See `config/sources.yaml` for the
complete license registry.

## License

See `LICENSE`.
