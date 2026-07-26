<div align="center">

# 🏦 BankLens

**An MCP-powered bank-intelligence platform — built once, consumed three ways.**

One medallion data pipeline over real public filings → six analyst-grade features → a governed MCP tool surface → an AI-agent fleet and a quant-terminal UI.

</div>

---

## What this is

BankLens turns scattered public bank filings (FDIC, FFIEC, SEC EDGAR, Fed NIC, EBA) and live market data into concrete analyst tools: hidden-risk detection, filing-change tracking, deposit-flight early warning, behavioural peer grouping, M&A fit-finding, and real-balance-sheet stress testing — usable by a human (UI), a machine (CLI/SDK), or an AI agent (MCP), all on the **same Gold feature layer**.

> **Core principle:** build the Gold layer once; every feature, tool, and agent reads from it. No feature re-derives raw data.

Full plan: [`docs/architecture/BankLens-Master-Architecture-Plan.md`](docs/architecture/BankLens-Master-Architecture-Plan.md) · Learn the domain: [`docs/domain/BankLens-Domain-Study-Guide.md`](docs/domain/BankLens-Domain-Study-Guide.md)

---

## Quick start — the Phase-1 vertical slice (no installs)

Everything you need for the first slice is already standard Python 3.11+. Pull one real bank end-to-end (fetch → Bronze → Silver → Gold):

```powershell
# from the repo root
powershell -File scripts/run_vertical_slice.ps1               # Wells Fargo (CERT 3511)
powershell -File scripts/run_vertical_slice.ps1 -Cert 628     # JPMorgan Chase
powershell -File scripts/run_tests.ps1                        # run the metric tests
```

You'll see the balance sheet, the derived Gold features (uninsured-deposit %, loan-to-deposit, QoQ deltas), and the raw/normalised JSON written under `data/`.

Some well-known FDIC certificate numbers: `628` JPMorgan Chase · `3510` Bank of America · `7213` Citibank · `3511` Wells Fargo · `6548` U.S. Bank · `6976` Dime Community.

### The five working features

```powershell
powershell -File scripts/run_vertical_slice.ps1 -Cert 6976   # F11 Balance-Sheet X-Ray
powershell -File scripts/filing_diff.ps1 -Cert 3511          # F12 Filing Diff
powershell -File scripts/cluster_report.ps1                  # F14 Peer Clustering
powershell -File scripts/ma_fit.ps1 -TargetCert 6976         # F15 M&A Fit
powershell -File scripts/stress_test.ps1 -Cert 6976 -Outflow 60 -RateBps 400  # F16 Stress
powershell -File scripts/deposit_flight.ps1                  # F13 Deposit-Flight ML (showcase)
powershell -File scripts/population_report.ps1               # peer percentiles
```

### One backend, three consumers — the MCP surface

The same feature logic is exposed as MCP tools (JSON-RPC over stdio, audited):

```powershell
powershell -File scripts/mcp_demo.ps1     # drive the server, see all tools called
```

Open this repo in **Claude Code** and approve the `banklens` server (from
[`.mcp.json`](.mcp.json)) to ask, e.g., *"stress-test cert 6976 under a 60% deposit run"*.

### The quant terminal (Phase 7)

A real-data React/TypeScript dashboard over all 6 features — X-Ray, Filing Diff, Peer
Clusters, Deposit-Flight Risk, M&A Fit, and a live Stress Simulator with interactive
sliders — plus a 1,000+ bank peer-position scatter. No mock data anywhere.

```powershell
powershell -File scripts/dev_web.ps1   # bridge (8791) + Vite dev server (5173)
```

See [`frontend/apps/web/README.md`](frontend/apps/web/README.md).

### The agent fleet (Phase 6)

A supervisor routes your question to a specialist (Risk / Filings / M&A / Macro),
which chains the MCP tools — nothing but MCP — to build an answer:

```powershell
# needs your own ANTHROPIC_API_KEY (env var or .env) — see services/agents/README.md
powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
```

---

## Repository layout

```
banklens/
├── docs/            Architecture plan, ADRs, C4, domain study guide, data contracts
├── schemas/         Cross-language contracts — protobuf, JSON-Schema, Avro
├── config/          Environment config + the data-source registry (with license tags)
├── pipelines/       THE DATA PLATFORM  (runnable now)
│   ├── ingestion/     Python reference connectors → Bronze  ← Phase 1 lives here
│   ├── transforms/    Bronze→Silver→Gold reference math     ← Phase 1/2
│   ├── dbt/           Silver/Gold transforms at scale        (Phase 2)
│   ├── dagster/       Orchestration / software-defined assets (Phase 1–2)
│   └── spark/         Distributed backfills                  (Phase 2)
├── services/        Deployable services (polyglot)
│   ├── ingestion/       Rust connector SDK (production target for pipelines/ingestion)
│   ├── feature-services/ gRPC services: xray, filing-diff, peer-cluster, ma-fit, risk-score
│   ├── stress-engine/    Rust deterministic capital-buffer simulator (Phase 3)
│   ├── mcp-server/       MCP tool surface (Phase 5)
│   ├── agents/           Agentic AI fleet (Phase 6)
│   └── api-gateway/      Edge gateway
├── ml/              ML platform: deposit_flight (F13), peer_clustering (F14), feature_store
├── frontend/        TypeScript quant terminal (candles, treemaps, heatmaps)  (Phase 7)
├── libs/            Shared libraries per language (python / rust / ts)
├── platform/        Infra-as-code: terraform, helm, k8s, docker, observability
├── tests/           Cross-cutting integration / e2e / data-quality suites
├── scripts/         Dev entry points (run_vertical_slice, run_tests, bootstrap)
└── data/            Local Bronze/Silver/Gold (git-ignored)
```

---

## Roadmap (see the master plan for detail)

| Phase | Focus | Status |
|------:|-------|--------|
| 0 | Foundations — arch, IaC, CI | scaffolded |
| 1 | Data platform — Bronze + Silver ingestion | reference done |
| 2 | Gold layer + peer percentiles (market/time-series pending) | Gold done |
| 3 | Deterministic features — X-Ray, Diff, Peers, M&A, Stress | ✅ (reference) |
| 4 | Deposit-Flight ML model (showcase) | ✅ AUC 0.99, SVB flagged leave-one-out |
| 5 | MCP server & tooling — 9 tools, all 6 features | ✅ reference done |
| 6 | Agentic AI layer — supervisor + 4 specialists over MCP | ✅ reference done |
| 7 | Quant-terminal UI (X-Ray, Diff, Clusters, Risk, M&A, Stress, peer scatter) | ✅ reference done |
| 6 | Agentic AI layer | planned |
| 7 | Quant-terminal visualization | planned |
| 8 | Hardening, security, DR & GA | planned |

## Tooling as phases arrive

Installed and sufficient for Phase 1: **Python 3.11+, Git**. Add later, per phase:
`uv` (Python envs, Phase 1–2) · **Docker** infra via `platform/docker` (Phase 1–2) · **Rust** toolchain (Phase 3 engines) · **dbt** (Phase 2) · **JDK/Spark** or Databricks (Phase 2) · `kind`/`minikube` for K8s (Phase 8).

---

## Data & licensing

Government sources (FDIC, FFIEC, SEC, Fed, FRED, EBA) are public-domain and safe to redistribute internally. Commercial market data is **licensed** — see [`config/sources.yaml`](config/sources.yaml); the serving/MCP layer enforces those license tags. Scrapers respect `robots.txt` and documented rate limits; bulk/API first, scrape last.

## License

See [`LICENSE`](LICENSE) — placeholder pending the company's choice.
