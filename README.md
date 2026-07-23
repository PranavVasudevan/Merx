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

Some well-known FDIC certificate numbers: `628` JPMorgan Chase · `3510` Bank of America · `7213` Citibank · `3511` Wells Fargo · `6548` U.S. Bank.

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
| **1** | **Data platform — Bronze + Silver ingestion** | **in progress** |
| 2 | Gold layer, time-series & market data | next |
| 3 | Deterministic features (X-Ray, Diff, Peers, Stress) | planned |
| 4 | Deposit-Flight ML model (showcase) | planned |
| 5 | MCP server & tooling | planned |
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
