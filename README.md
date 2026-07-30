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
powershell -File scripts/run_tests.ps1                        # full suite: 23 files, 135 tests
```

You'll see the balance sheet, the derived Gold features (uninsured-deposit %, loan-to-deposit, QoQ deltas), and the raw/normalised JSON written under `data/`.

Some well-known FDIC certificate numbers: `628` JPMorgan Chase · `3510` Bank of America · `7213` Citibank · `3511` Wells Fargo · `6548` U.S. Bank · `6976` Dime Community.

### The five working features

```powershell
powershell -File scripts/run_vertical_slice.ps1 -Cert 6976   # F11 Balance-Sheet X-Ray
powershell -File scripts/filing_diff.ps1 -Cert 3511          # F12 Filing Diff
powershell -File scripts/cluster_report.ps1                  # F14 Peer Clustering
powershell -File scripts/land_sod.ps1                         # land real branch footprint (keyless, one-time)
powershell -File scripts/ma_fit.ps1 -TargetCert 6976         # F15 M&A Fit (real branch-overlap geography)
powershell -File scripts/stress_test.ps1 -Cert 6976 -Outflow 60 -RateBps 400  # F16 Stress
powershell -File scripts/deposit_flight.ps1                  # F13 Deposit-Flight ML (showcase)
powershell -File scripts/population_report.ps1               # peer percentiles
powershell -File scripts/crosswalk.ps1 -Verify ZIONS          # CERT<->CIK<->RSSD, live cross-source check
powershell -File scripts/land_market_data.ps1                 # real EOD candles (needs your own free TIINGO_API_KEY)
```

### One backend, three consumers — the MCP surface

The same feature logic is exposed as MCP tools (JSON-RPC over stdio, audited):

```powershell
powershell -File scripts/mcp_demo.ps1     # drive the server, see all tools called
```

Open this repo in **Claude Code** and approve the `banklens` server (from
[`.mcp.json`](.mcp.json)) to ask, e.g., *"stress-test cert 6976 under a 60% deposit run"*.

### The quant terminal (Phase 7 + 2a)

A real-data React/TypeScript dashboard over all 6 features — X-Ray, Filing Diff, Peer
Clusters, Deposit-Flight Risk, M&A Fit, and a live Stress Simulator with interactive
sliders — plus a 1,000+ bank peer-position scatter and **real candlestick charts**
(TradingView's `lightweight-charts`, real Tiingo EOD data). No mock data anywhere.

```powershell
powershell -File scripts/dev_web.ps1   # bridge (8791) + Vite dev server (5173)
```

Real candles need `scripts/land_market_data.ps1` first, which needs your own free
`TIINGO_API_KEY` (get one at https://api.tiingo.com/account/api/token — the one
BankLens source that isn't keyless). Without it, the chart shows an honest
"no data landed yet" message rather than a placeholder or fake series.

See [`frontend/apps/web/README.md`](frontend/apps/web/README.md).

### The agent fleet (Phase 6) — $0 by default, real bugs found running it live

A supervisor routes your question to a specialist (Risk / Filings / M&A / Macro),
which chains the MCP tools — nothing but MCP — to build an answer. **Default
provider is Ollama** (free, local, works with no setup) — this project has a hard
$0 spending rule. Gemini (also free, multi-key rotation like project-matcher's
`gemini_keys.py`) and Anthropic (costs money) are fully built and swappable via
`--provider`, but weren't run live in this environment.

```powershell
powershell -File scripts/agent_ask.ps1 "which banks look most exposed to a deposit run right now?"
```

Running this for real (`llama3.2:1b`) surfaced and fixed three genuine bugs — a
string-vs-integer type mismatch at the MCP boundary, a small model looping on
duplicate tool calls instead of answering, and a stray tool-call artifact standing
in for a final answer. See [`services/agents/README.md`](services/agents/README.md)
for the full story; the fixed loop now produces coherent, correct, fully-local
answers grounded in real tool data.

### Containerized (Phase 8, started) — real build, real run, verified end-to-end

```powershell
powershell -File scripts/docker_up.ps1
# open http://localhost:8080
```

**Actually built and run, not just written:** both images build cleanly and the
full app tier — bridge + quant terminal — was confirmed working end-to-end in a
browser against the real containers (zero console errors, real Silver/Gold/X-Ray/
clustering/stress/M&A/risk-score data). A real bug was found and fixed this way:
the bridge image was missing `ml/` (the trained deposit-flight model card), which
surfaced as an honest "model not trained yet" error rather than silently serving
wrong data — fixed by adding it to the Dockerfile like source, not runtime data.

### On Kubernetes (Phase 8) — also deployed and verified for real

```powershell
powershell -File scripts/k8s_dev_up.ps1     # build, load data into a PVC, deploy
kubectl port-forward -n banklens-dev svc/banklens-bridge 8791:8791   # 2nd terminal
kubectl port-forward -n banklens-dev svc/banklens-web 8080:80        # 3rd terminal
```

Deployed to a real cluster (Docker Desktop k8s v1.36.1) with the whole UI verified
in a browser against it. Doing it for real surfaced three gotchas that reading docs
wouldn't have: Docker Desktop's k8s is **kind-based**, so `hostPath` can't reach
your files at all (hence a PVC), mutable image tags are silently stale in its
containerd (hence a unique tag per deploy), and NodePorts aren't published to
Windows (hence `port-forward`). All three are written up in
[`platform/k8s/README.md`](platform/k8s/README.md).

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
| 1 | Data platform — Bronze + Silver ingestion (FDIC, SEC, CERT↔CIK↔RSSD crosswalk) | ✅ reference done |
| 2 | Gold layer + peer percentiles | ✅ Gold done |
| 2a | Market EOD prices (Tiingo) + real candlestick charts | ✅ built, needs user's own free key to land data |
| 3 | Deterministic features — X-Ray, Diff, Peers, M&A, Stress | ✅ reference done — M&A's geo-overlap now real FDIC branch data (found & worked around a real FDIC data-quality bug, see ma-fit README) |
| 4 | Deposit-Flight ML model (showcase) | ✅ AUC 0.94, pooled across 2023 + 2008 crises — SVB/Signature/First Republic flagged, IndyMac honestly not (different failure archetype) |
| 5 | MCP server & tooling — 11 tools, all 6 features + market data | ✅ reference done |
| 6 | Agentic AI layer — supervisor + 4 specialists, 3 providers (Ollama/Gemini/Anthropic) | ✅ reference done, live-tested on Ollama |
| 7 | Quant-terminal UI (X-Ray, Diff, Clusters, Risk, M&A, Stress, peer scatter, candles) | ✅ reference done |
| 8 | Hardening, security, DR & GA | 🟡 containerization + K8s **deployed and verified on a real cluster**; CI made real (full suite + blocking lint). Security/DR/GA not started |

## Tooling as phases arrive

Installed and sufficient for Phase 1: **Python 3.11+, Git**. Add later, per phase:
`uv` (Python envs, Phase 1–2) · **Docker** infra via `platform/docker` (Phase 1–2) · **Rust** toolchain (Phase 3 engines) · **dbt** (Phase 2) · **JDK/Spark** or Databricks (Phase 2) · `kind`/`minikube` for K8s (Phase 8).

---

## Data & licensing

Government sources (FDIC, FFIEC, SEC, Fed, FRED, EBA) are public-domain and safe to redistribute internally. Commercial market data is **licensed** — see [`config/sources.yaml`](config/sources.yaml); the serving/MCP layer enforces those license tags. Scrapers respect `robots.txt` and documented rate limits; bulk/API first, scrape last.

## License

See [`LICENSE`](LICENSE) — placeholder pending the company's choice.
