# BankLens — Master Architecture & Delivery Plan
### Production-grade, enterprise bank-intelligence platform
**Author:** Principal Systems Architect (draft v1.0)
**Horizon:** ~14 months to GA, then continuous evolution
**Status:** Foundational blueprint. Everything here is the base layer; the six features in the source plan are the *first wave* — the platform is designed so later derivative features are cheap to add.

---

## 0. How to read this document

The original `banklens_project_plan.md` is a good *product* spec (six features, medallion idea, MCP idea). This document is the *engineering & systems* plan that turns it into something a bank could actually run in production for years. It makes concrete, defensible decisions on:

- **Languages & frameworks** (polyglot: Rust / C++ / JVM / Python / TypeScript — each where it earns its place in fintech)
- **The medallion data platform** (lakehouse on Iceberg/Delta, Databricks vs. sovereign OSS)
- **Databases** (Postgres, DuckDB, ClickHouse, pgvector — and *why not* Cassandra)
- **Real, accessible datasets** (FDIC, FFIEC, SEC EDGAR, Fed NIC, EBA, FRED, market OHLC) with volumes and licensing
- **MCP server + agentic AI** as first-class citizens, not bolt-ons
- **A quant-grade visualization terminal** (candles, market-cap treemaps, heatmaps, peer networks, stress waterfalls)
- **Kubernetes + Docker topology** sized deliberately small
- **Security, compliance, observability, DR** to enterprise standard
- **A phased roadmap** (Phase 0–9) spanning ~14 months with exit criteria

Guiding principle throughout, straight from the source plan and non-negotiable: **build the Gold layer once; every feature, tool, and agent reads from it. No feature re-derives raw data.**

---

## 1. Guiding principles & architectural tenets

1. **One pipeline, many consumers.** UI, CLI/SDK, MCP tools, and AI agents all sit on the *same* Gold layer and the *same* feature services. Logic is never duplicated per consumer.
2. **Openness over lock-in.** Open table formats (Apache Iceberg / Delta), open protocols (Arrow, gRPC, OpenTelemetry, OIDC), so the platform runs on-prem, on LinuxONE, or in any cloud without a rewrite.
3. **Right tool, right language.** Deterministic hot-path math and ingestion in Rust/C++; distributed transforms on the JVM/Spark; data science in Python; UI in TypeScript. Polyglot, but *disciplined* — every language has a clear domain.
4. **Auditability is a feature, not a log line.** Every tool call, model prediction, agent action, and data transformation is traceable end-to-end. This is a bank; lineage and reproducibility are requirements.
5. **Everything is a versioned contract.** Data contracts (schemas), API contracts (protobuf/OpenAPI), MCP tool contracts, and model contracts (model cards) are all versioned and tested in CI.
6. **Determinism where money is involved.** The stress simulator and capital-ratio math are pure, auditable, property-tested functions — never an opaque model.
7. **Small blast radius.** Modest, well-utilised Kubernetes footprint; scale by node-pool sizing and autoscaling, not by node sprawl.

---

## 2. Deployment posture & core assumptions

**The ask:** "assume we are working with the mainframe … we can make use of cloud." I'm resolving this into an explicit, realistic enterprise posture:

> **On-prem / sovereign-first, cloud-portable, mainframe-integrated.**

- The analytics platform is **containerised x86-64/Linux (or IBM LinuxONE / Linux on Z)** running on **Kubernetes** in the bank's own data center. Nobody runs Spark ML or ClickHouse on z/OS core banking — so the mainframe is treated as an **integration source/sink**, not the compute host.
- **Mainframe integration seam:** IBM MQ / Kafka Connect bridges pull reference and (if ever needed) internal core-banking extracts into Bronze. If the bank runs **IBM LinuxONE**, our exact same container images run there — that satisfies "working with the mainframe" without abandoning the modern stack.
- **Cloud-portable:** because storage is S3-compatible object storage and tables are open (Iceberg/Delta), the *same* platform lifts to AWS/Azure/GCP or Databricks with only the storage endpoint and secrets changing. We pick **one** managed-vs-sovereign option per environment (see §5.6), not both at once.
- **Recommended concrete choice for the enterprise build:** hybrid — **sovereign OSS lakehouse on-prem for the system of record + regulated data**, with **Databricks (or equivalent) as an optional elastic burst tier** for heavy backfills and model training. If a single choice is mandated, go **Databricks Lakehouse** for time-to-value and governance (Unity Catalog lineage), and keep the OSS stack documented as the exit path.

Everything below is written to run in *either* world.

---

## 3. Data sourcing — real, accessible, and large (no mocks)

All primary sources are **public, free, and API/bulk-accessible today**. I verified them during planning. This is the fuel for every feature and for the candle/market-cap visualizations.

### 3.1 Core regulatory & fundamentals sources

| Source | What it gives | Access | Cadence | Approx. volume |
|---|---|---|---|---|
| **FDIC BankFind Suite API** (`banks.data.fdic.gov`) | Full US bank financials, institutions, branches (SOD), failures, demographics. ~4,500 FDIC-insured institutions. REST, **no auth**. | REST API + bulk download | Quarterly | ~4,500 banks × ~1,000+ fields × quarterly × decades → tens of millions of rows |
| **FFIEC CDR Public Data Distribution** (`cdr.ffiec.gov`) | Call Report facsimiles (every line item) + **UBPR** with peer-group averages & percentile ranks. Tab-delimited **and XBRL**. Available ~45 days after quarter-end via the **Public Web Service (PWS)** for automated pulls. | Bulk ZIP per quarter + PWS SOAP | Quarterly | Each quarterly ZIP is large (all banks × thousands of MDRM items) |
| **SEC EDGAR** (`data.sec.gov`) | Richer disclosures for *listed* banks: 10-K/10-Q, footnotes, risk-factor **text**, XBRL facts. APIs: **CompanyFacts**, **CompanyConcept**, **Frames**. Nightly **`companyfacts.zip`** bulk. **No auth**, **10 req/s** limit. | REST + nightly bulk | Continuous / quarterly | companyfacts.zip is ~GB-scale; full filing archive is very large |
| **Federal Reserve NIC — FR Y-9C / Y-9LP / Y-9SP** (`ffiec.gov/npw`) | Bank/savings & loan **holding-company** consolidated financials (the parent-level view FDIC lacks). Quarterly ZIPs back to **1986/2000**. | Financial Data Download (ZIP) | Quarterly | Decades × all holding cos |
| **FDIC Summary of Deposits (SOD)** | Branch-level geographic footprint (needed for M&A geo-overlap, feature 15). | Bulk CSV / API | Annual | ~80k+ branch records/yr |
| **Historical failure set** | FDIC failed-bank list + case detail (SVB, Signature, First Republic, WaMu, IndyMac, …) → labeled positives for feature 13. | CSV / curated | Static | Hundreds of labeled events |

**Identity crosswalk (critical, build early):** FDIC **CERT** ↔ SEC **CIK** ↔ Fed **RSSD ID** ↔ ticker. The RSSD is the linchpin that joins FDIC bank-level, Fed holding-company, and SEC filer data. This crosswalk is its own Silver-layer asset with tests.

### 3.2 Market & macro sources (for the quant/visualization side)

| Source | What it gives | Access | Notes |
|---|---|---|---|
| **Market OHLC / candles** — Polygon.io, Tiingo, Alpha Vantage, Financial Modeling Prep, Marketstack | Daily & intraday OHLCV, market cap, corporate actions for **listed bank tickers** (JPM, BAC, WFC, regional banks, KRE/KBE ETFs). | REST/WebSocket; free tiers = EOD, paid = intraday/real-time | **Licensing matters** — see §3.4. Start with EOD free tier; upgrade one vendor for intraday. |
| **FRED** (St. Louis Fed) | Macro overlays: Fed funds, Treasury yield curve, unemployment, CPI, bank credit aggregates, deposit series. API key, JSON/CSV. | REST | Decades of series; drives rate-shock scenarios in the stress simulator |
| **EBA EU-wide Transparency Exercise + Risk Dashboard** (`eba.europa.eu`, EUCLID) | 119 EU/EEA banks, **1.3M+ data points**, CET1/NPL/LCR. Bank-by-bank, multiple reference dates. | Downloadable datasets | The EU-comparison angle; stretch goal for MVP, first-class later |

**Why this matters for the "quant environment" ask:** FDIC/FFIEC give the *fundamentals* (balance sheets, ratios) → drive the analytical charts (heatmaps, treemaps, percentile bands). Market OHLC gives the *price action* → drive candlestick charts, market-cap tiles, volatility overlays. FRED gives the *macro backdrop* → drives stress-test scenarios and yield-curve panels. Together they make a real quant terminal, not a static dashboard.

### 3.3 Scraper / connector framework

Prefer official bulk & APIs; scrape only what has no API (e.g., some EBA XLS artifacts, certain FDIC PDFs, press-release failure detail).

- **Language:** **Rust** (`reqwest` + `tokio` + `scraper`/`select`), chosen for throughput, memory safety on long backfills, and clean concurrency for polite parallel crawling.
- **Design:** a generic **Connector SDK** — each source implements a `Source` trait (`discover → fetch → checksum → land`). Connectors emit **provenance metadata** (source URL, fetch time, ETag/checksum, license tag) with every Bronze record.
- **Politeness & legality (non-negotiable):** respect `robots.txt`, obey documented rate limits (e.g., SEC **10 req/s**), exponential backoff, per-host concurrency caps, and identifiable User-Agent with contact. Bulk/API first, scrape last.
- **Idempotency & backfill:** content-addressed landing (checksum dedupe) so re-runs never double-count; full-history backfill jobs are resumable.

### 3.4 Data governance & licensing (architect's honest note)

- Government sources (FDIC, FFIEC, SEC, Fed, FRED, EBA) are **public/open** — safe to store and redistribute internally.
- **Commercial market-data vendors are NOT** — their OHLC is licensed. Redistribution, and sometimes even display, is contractually limited. **Action:** a **data-license registry** (a governed table) tags every dataset with its license and allowed uses; the serving layer and MCP tools **enforce** it (e.g., "market data visible in UI, but not returned in bulk via public MCP tool"). This is a real enterprise control, and it's cheap to add early and expensive to retrofit.

---

## 4. Language & framework decisions (the polyglot map)

The ask was explicit: use languages common in fintech, complicate as needed, production-grade. Here is the disciplined split — each language owns a domain and is justified.

| Layer / concern | Language | Framework(s) | Why this language here |
|---|---|---|---|
| **Ingestion, scrapers, connectors** | **Rust** | tokio, reqwest, arrow-rs, object_store | Long-running backfills need memory safety + high concurrency; Arrow-native writes to the lakehouse; no GC pauses on big pulls |
| **Deterministic financial engines** (Capital Buffer Simulator, ratio math, risk kernels) | **Rust** (+ **C++** for the quant kernel) | Rust core; **QuantLib (C++)** via FFI for fixed-income/duration analytics | Money math must be fast, auditable, and correct; Rust gives safety, QuantLib gives battle-tested quant finance primitives (duration, curves) |
| **Real-time market-data / tick processing → candles** | **Rust** (or **C++** for ultra-low latency) | tokio + WebSocket consumers → ClickHouse | Streaming aggregation of ticks into OHLC bars is a classic low-latency, high-throughput job |
| **Distributed medallion transforms** (Bronze→Silver→Gold at scale, backfills) | **JVM: Scala/PySpark** | **Apache Spark** (Databricks or OSS), **dbt** for SQL models | The industry-standard distributed transform engine; dbt gives tested, documented SQL for Silver/Gold |
| **Data science / ML** (features 13, 14; SHAP, calibration) | **Python** | scikit-learn, XGBoost, SHAP, PyTorch (optional temporal), pandas/Polars | The ML ecosystem lives here; Polars for fast single-node frames |
| **Orchestration** | **Python** | **Dagster** (software-defined assets) or Airflow | Asset-based orchestration maps 1:1 to Bronze/Silver/Gold assets with built-in lineage |
| **MCP server** | **Python** (MVP) → **Rust** hot path (prod) | Official **MCP SDK**; thin orchestration calling gRPC backends | Fastest path to correct tool contracts; heavy compute stays in Rust/Spark behind it |
| **Agentic AI** | **Python** | **Claude Agent SDK / LangGraph**, Anthropic API (Opus 4.8 / Sonnet 5 / Haiku 4.5) | Best agent tooling + tracing; agents call MCP tools, not databases directly |
| **Internal service APIs / gateways** | **Go** or **Rust** | gRPC + REST gateway (Connect/Envoy) | Small, fast, statically-linked service binaries; either is fine — pick one and standardize |
| **Frontend / quant terminal** | **TypeScript** | **Next.js/React**, TradingView Lightweight Charts, ECharts, visx/D3, deck.gl, TanStack Query | Rich, real-time, accessible UI; best-in-class financial charting |
| **Infra as code / glue** | **HCL + YAML + Python** | Terraform, Helm/Kustomize, Argo CD | GitOps, reproducible environments |

**Decisive recommendation:** don't over-fragment. The *spine* is **Rust (engines/ingest) + Spark/JVM (transforms) + Python (ML/agents/orchestration) + TypeScript (UI)**. **C++ is scoped narrowly** to the QuantLib-based quant kernel and (optionally) the tick handler — introduce it only in Phase 3+ when the duration/curve math demands it. Resist adding more languages.

---

## 5. Data platform, storage & the medallion architecture

### 5.1 Medallion layers

- **Bronze (raw, immutable, append-only):** exact source bytes + provenance metadata, partitioned by source/period. Table format: **Apache Iceberg** (open, engine-agnostic) or **Delta Lake** (if Databricks). Object storage: **MinIO** on-prem / **S3** in cloud. Supports full reprocessing and audit.
- **Silver (normalized, conformed):** the canonical **`bank_financials`** (one row per bank per quarter) + `holdco_financials` (FR Y-9C) + `crosswalk` (CERT/CIK/RSSD/ticker) + `branches` (SOD) + `filings_text` (SEC narrative). Cleaning: identifier standardization, restated-filing dedupe, range validation, explicit missing-value flags (never silent zero-fill).
- **Gold (derived, reusable features):** exactly as the source plan specifies — `qoq_delta_*`, `concentration_ratio_*`, `uninsured_deposit_pct`, `funding_stability_score`, `peer_cluster_id`, `growth_rate_3yr`, `percentile_rank_*` (vs. all banks *and* vs. peer cluster). Plus market-derived Gold: `market_cap`, `price_vol_30d`, `pb_ratio`. **This is the contract every feature/tool/agent reads.**

Transforms are **dbt models + PySpark** with tests at each layer (schema, null thresholds, referential integrity, business rules). Orchestrated as **Dagster assets** so lineage is automatic and any Gold column is traceable to its Bronze source.

### 5.2 The database decision (explicitly what you asked)

Different jobs, different engines. This is the senior answer to "DuckDB vs Cassandra vs Postgres":

| Role | Engine | Rationale |
|---|---|---|
| **Lakehouse tables (Bronze/Silver/Gold)** | **Iceberg/Delta on object storage** | Cheap, open, huge scale, time-travel, engine-agnostic. The system of *analytical* record. |
| **OLTP system-of-record** — users, RBAC, MCP call audit log, agent memory/state, job metadata, data-license registry | **PostgreSQL** | Rock-solid ACID, mature, does everything an app backend needs; +**pgvector** for embeddings so we don't add another store yet |
| **Per-request analytical queries** — feature services & MCP tools querying Gold fast, no cluster | **DuckDB (embedded)** | Exactly the "speed" case you flagged: columnar, vectorized, reads Parquet/Iceberg directly, runs *inside* the service process. Sub-second analytics with zero infra. **This is where DuckDB shines.** |
| **High-volume time-series serving** — market OHLC, metric history → candlestick charts, heatmaps, market-cap tiles | **ClickHouse** | Purpose-built for time-series/OLAP at high cardinality; powers real-time candle aggregation and dashboard queries far better than Postgres |
| **Vector search** — RAG over 10-K/10-Q risk-factor text & footnotes | **pgvector** (start) → **Qdrant** (if scale/latency demands) | Keep the stack lean; graduate only when needed |
| **Cache / rate-limit / ephemeral queues** | **Redis** | Standard |
| **Event backbone** | **Kafka** (or **Redpanda** for a lighter on-prem footprint) | Ingestion events, market ticks, CDC, agent tool-call events |

**Why *not* Cassandra (considered and rejected):** Cassandra is superb for write-heavy, globally-distributed, always-on *operational* workloads with simple access patterns. Our workload is the opposite: **read-heavy analytics with rich, ad-hoc queries and aggregations** over quarterly-batch data. ClickHouse + DuckDB + Postgres cover every access pattern with less operational burden and better analytical ergonomics. Cassandra would add a distributed-systems tax for no benefit here. *Revisit only* if we later need a geo-distributed, multi-region, high-write operational tier (e.g., global real-time tick capture at massive scale) — and even then ScyllaDB or ClickHouse-Keeper would be evaluated first.

### 5.3 Streaming & orchestration

- **Kafka/Redpanda** as the backbone; **Debezium** CDC from Postgres → lakehouse for a fully auditable change history of operational data.
- **Real-time candles:** Rust WebSocket consumers (or **Flink** if complexity grows) aggregate market ticks into OHLC bars → ClickHouse → WebSocket push to the UI.
- **Batch/medallion:** **Dagster** schedules quarterly ingest → Bronze → Silver → Gold, with sensors that trigger on new FFIEC/FDIC/SEC drops (e.g., the ~45-day-after-quarter FFIEC release).

### 5.4 Data quality & lineage

- **Great Expectations / Soda** checks as gates between layers (fail the pipeline, don't publish bad Gold).
- **OpenLineage + Marquez** (or **Unity Catalog** on Databricks) for column-level lineage.
- **Data contracts** in version control; breaking schema changes fail CI.
- **Evidently** for feature/label drift on the ML side.

### 5.5 Approximate scale & why a lakehouse

FDIC (~4,500 banks × ~1,000 fields × quarterly × decades) + FFIEC facsimiles (thousands of MDRM items/bank/quarter) + SEC companyfacts (GB-scale nightly) + decades of market OHLC (billions of bars at intraday granularity) = comfortably **tens–hundreds of GB of curated data, TB-scale of raw+historical+intraday**. That's too big and too query-diverse for a single Postgres, and perfectly suited to a **lakehouse (cheap object storage, open tables) + ClickHouse (hot time-series) + DuckDB (fast per-request)** split. It is *not* "big data" in the petabyte sense — so we deliberately avoid over-engineering (no 50-node clusters).

### 5.6 Databricks vs. sovereign OSS (decision matrix)

| Dimension | Databricks Lakehouse | Sovereign OSS (Spark + Iceberg + MinIO + Nessie/Polaris) |
|---|---|---|
| Time-to-value | ✅ Fastest | ⚠️ More assembly |
| Governance/lineage | ✅ Unity Catalog built-in | ⚠️ OpenLineage/Marquez + OPA — capable, more work |
| Data sovereignty / air-gap / "mainframe" posture | ⚠️ Cloud-first | ✅ Runs fully on-prem / LinuxONE |
| Cost model | Consumption (can spike on backfills) | CapEx + ops labor |
| Lock-in | ⚠️ Higher | ✅ Open formats, portable |
| **Recommendation** | Use as **elastic training/backfill burst tier** or if a single managed choice is mandated | Use as the **on-prem system of record** for regulated data (fits the sovereign/mainframe posture) |

---

## 6. ML / MLOps platform

Powers feature 13 (Deposit-Flight classifier) and feature 14 (Peer clustering), and any future models.

- **Tracking & registry:** **MLflow** (works standalone or on Databricks).
- **Feature store:** **Feast** (or Databricks Feature Store) sourced from Gold — guarantees training/serving parity and prevents leakage.
- **Training:** scikit-learn (baselines: logistic regression, K-Means/GMM), **XGBoost** (feature 13), **SHAP** for interpretability, optional **PyTorch** temporal model (sequence of quarters → run-risk) if the tabular model plateaus.
- **Validation rigor (this is what makes feature 13 defensible):** strict **temporal splits** (no lookahead), **leakage audits** (a bank's *post*-failure quarters can't inform its *pre*-failure prediction), **calibration** (probabilities must mean something), **backtest harness** — "given only data available at 2022-Q4, would the model have flagged SVB before March 2023?" is the headline demo and a *test in CI*.
- **Serving:** models exported to **ONNX**, served via a **FastAPI/BentoML** microservice (or **Rust `ort`** for the hot path), behind the MCP `get_risk_score` tool.
- **Governance:** **model cards**, drift monitors (Evidently), scheduled retraining with challenger/champion promotion, and a human sign-off gate before a new risk model goes live (this is a bank).

---

## 7. MCP server — design

The MCP server is the **single API surface** that UI, CLI/SDK, and AI agents share. It is **thin orchestration**; all heavy compute lives in the Rust engines, ClickHouse, DuckDB, and ML services behind it.

**Tool contracts (from the source plan, plus quant/market additions):**

```
# Core (source plan)
list_banks(query, filters)                    → search/filter by name, state, size, cluster
get_bank_profile(bank_id, quarter)            → Silver/Gold core data for one bank
get_bank_xray(bank_id)                         → feature 11 (concentration risk)
diff_filings(bank_id, quarter_a, quarter_b)    → feature 12 (filing diff)
get_risk_score(bank_id)                        → feature 13 (deposit-flight + SHAP drivers)
get_peer_cluster(bank_id)                      → feature 14 (behavioral peers)
find_ma_matches(bank_id, top_n)                → feature 15 (M&A fit)
run_stress_test(bank_id, shock_params)         → feature 16 (capital buffer sim)
compare_banks(bank_id_list, metrics)           → side-by-side

# Quant / market additions (new)
get_price_candles(ticker, interval, range)     → OHLCV for candlestick charts
get_market_snapshot(bank_id)                   → market cap, P/B, 30d vol, price
get_macro_series(series_id, range)             → FRED overlays (rates, yields)
search_filings_text(query, filters)            → RAG over 10-K/10-Q narrative
```

**Cross-cutting MCP concerns (enterprise-grade):**
- **AuthN/Z:** OIDC (Keycloak) + **OPA** policy per tool (who can call what, and the data-license registry enforced here).
- **Audit:** every call logged (tool, args hash, requester, bank_id, timestamp, latency, result hash) to Postgres → lakehouse. Satisfies the source plan's auditability requirement and then some.
- **Validation & versioning:** JSON-Schema-validated inputs/outputs; tools are versioned (`v1`, `v2`) so agents and UI don't break.
- **Rate limiting & quotas** (Redis) per principal.
- **Determinism contract:** read-only tools are side-effect-free and cacheable; any future write tool requires explicit human-in-the-loop approval.

---

## 8. Agentic AI layer

Agents are **consumers of MCP tools**, never of raw databases — this keeps all business logic and governance in one place.

- **Topology:** a **Supervisor/orchestrator agent** routes to **specialist agents**:
  - *Risk Analyst* — chains `list_banks → get_risk_score → get_bank_xray` to answer "which banks look most exposed to a deposit run right now, and why?"
  - *Filings Analyst* — `diff_filings` + `search_filings_text` for "what materially changed at Bank X this quarter?"
  - *M&A Scout* — `find_ma_matches` + `get_market_snapshot` for partner shortlists with rationale.
  - *Macro/Stress* — `get_macro_series` + `run_stress_test` for scenario analysis.
- **Framework:** **Claude Agent SDK / LangGraph**; models per task tier — **Opus 4.8** for hard multi-step reasoning, **Sonnet 5** for routine analysis, **Haiku 4.5** for cheap classification/routing.
- **Retrieval:** RAG over filing narrative (pgvector/Qdrant) so agents can *cite* the exact 10-K risk-factor language behind a numeric signal.
- **Guardrails & safety:** OTel tracing of every agent step, tool-call allow-lists, output validation, cost/latency budgets, and **human-in-the-loop approval** for anything side-effectful. Agent memory persisted in Postgres.
- **Evals:** a regression suite of analyst questions with graded expected tool-chains and answers, run in CI — agents are tested like code.

---

## 9. Visualization — the quant terminal (heavily emphasized)

A dedicated workstream, because "as much visualization as possible" is a stated priority. The UI should *feel* like a Bloomberg/quant terminal: dense, dark, real-time, keyboard-driven, multi-pane.

**Charting stack:**
- **Candlesticks / OHLCV + volume:** **TradingView Lightweight Charts** (open-source, renders 50k+ candles smoothly, 45KB) — the right tool for the price panels. Real-time updates over WebSocket from ClickHouse.
- **Analytical & quant charts:** **Apache ECharts** + **visx/D3** for:
  - **Market-cap treemap** (sector/peer, sized by cap, colored by QoQ move)
  - **Risk/ratio heatmaps** (banks × metrics, percentile-shaded)
  - **Peer-cluster network graph** (force-directed; feature 14) and **M&A fit graph** (feature 15)
  - **Stress-test waterfall** (feature 16: starting capital → each shock → ending ratio, pass/fail band)
  - **SHAP force / beeswarm plots** (feature 13 drivers — interpretable, not black-box)
  - **Percentile bands / distributions** (a bank vs. peers, feature 11)
  - **Yield-curve & rate panels** (FRED overlays)
  - **Filing-diff view** (feature 12: side-by-side with material-change highlights)
- **Geospatial:** **deck.gl / MapLibre** for SOD branch-footprint maps and M&A geographic-overlap.

**App stack:** Next.js + React + TypeScript, TanStack Query for data, WebSocket for live candles/ticks, a shared design system, full **accessibility** (WCAG) and **light/dark theming** (quant terminals default dark). Server-driven where possible; the same MCP/gRPC backend serves it.

---

## 10. Kubernetes & Docker topology (deliberately modest)

**Containerize everything** (the ask): multi-stage builds, **distroless** images for Rust/Go, pinned base images, SBOM per image, image signing (cosign), private registry (**Harbor** on-prem).

**Cluster (small on purpose — "not too many nodes"):**
- **3 control-plane** nodes (HA) + **~5–8 worker** nodes, organized into **node pools**:
  - *general* (APIs, MCP, UI, orchestrator) — 2–3 nodes
  - *memory-optimized* (Spark executors, ClickHouse) — 2–3 nodes
  - *ML/batch* (training, backfills; optional GPU) — 1–2 nodes, **scale-to-zero** when idle
- **Namespaces per domain:** `ingest`, `platform` (lakehouse/orchestration), `serving` (feature svcs, MCP), `ml`, `agents`, `ui`, `observability`, `security`.
- **Autoscaling:** HPA for stateless services, cluster-autoscaler / Karpenter-style scaling for batch bursts, KEDA for Kafka-lag-driven scaling. Scale by *sizing and autoscaling*, not node sprawl.
- **GitOps:** **Argo CD**; **Helm/Kustomize** charts; **Terraform** for cluster + cloud/on-prem infra.
- **Stateful services** (Postgres, ClickHouse, Kafka, MinIO) via battle-tested operators (CloudNativePG, Altinity ClickHouse operator, Strimzi, MinIO operator) with PVs on fast local/NVMe storage.
- **Runs identically on IBM LinuxONE** if the "mainframe" posture is taken literally (multi-arch images).

---

## 11. Security, compliance, governance & DR (bank-grade)

- **Identity:** OIDC via **Keycloak**; **RBAC + ABAC** enforced by **OPA/Gatekeeper**; least privilege everywhere.
- **Secrets:** **HashiCorp Vault** (dynamic DB creds, PKI, API-key rotation for market vendors).
- **Encryption:** TLS everywhere (mTLS between services via a light service mesh — Linkerd), encryption at rest on object store and DBs.
- **Network:** segmented namespaces, NetworkPolicies, egress control (scrapers can only reach allow-listed hosts).
- **Supply chain:** SBOMs, dependency & container scanning (Trivy/Grype), signed images (cosign), pinned deps, `cargo audit` / `pip-audit`.
- **Audit & lineage:** immutable audit log (MCP calls, agent actions, data transforms) in Postgres + lakehouse; column-level lineage.
- **Data governance:** the **data-license registry** (§3.4) is enforced at the serving/MCP boundary; PII is minimal (public filings) but market-data licensing is a real control.
- **Compliance alignment:** SOC 2-style controls, model-governance sign-off (SR 11-7-style model risk management for the risk model), reproducibility of every published number.
- **DR/BCP:** cross-site object-store replication, Postgres/ClickHouse backups + PITR, tested restore runbooks, RTO/RPO targets, chaos drills in Phase 8.

---

## 12. Observability

- **Metrics:** OpenTelemetry → **Prometheus** → **Grafana** (service SLOs, pipeline freshness, model-serving latency).
- **Logs:** **Loki**.
- **Traces:** **Tempo/Jaeger** — end-to-end across UI → MCP → feature service → engine → DB, and across agent tool-chains.
- **Data observability:** freshness/volume/schema-drift monitors on every medallion asset; alerts when a quarterly source is late or malformed.
- **Cost/FinOps:** OpenCost for cluster spend; Databricks/vendor cost dashboards for burst tiers.

---

## 13. Phased roadmap (~14 months to GA, then continuous)

Each phase has **objective / key deliverables / exit criteria**. Cross-cutting workstreams (Security, DataOps, MLOps, Observability, Governance) run *continuously* from Phase 0, not as a final bolt-on.

### Phase 0 — Discovery, architecture & foundations *(Month 1)*
- **Objective:** de-risk before building.
- **Deliverables:** requirements & data-licensing/legal review; threat model; **C4 architecture diagrams + ADRs**; monorepo + CI/CD skeleton; **Terraform** for a minimal K8s cluster (on-prem/LinuxONE or cloud); observability baseline (OTel/Prometheus/Grafana); data-contract conventions; the **data-license registry** schema.
- **Exit criteria:** "hello-world" service deploys via GitOps to the cluster with tracing/metrics/logs flowing; ADRs for language split, table format, and Databricks-vs-OSS signed off.

### Phase 1 — Data platform & ingestion: Bronze + Silver *(Months 2–3)*
- **Objective:** get real data in, normalized, end-to-end for **one bank first**, then scale to the MVP slice (US banks $1B–$250B assets, ~500–1,000 institutions).
- **Deliverables:** Rust **Connector SDK** + connectors for **FDIC, FFIEC (PWS), SEC EDGAR, Fed NIC FR Y-9C, FRED**; Bronze immutable landing (Iceberg/Delta on MinIO); Silver `bank_financials`, `holdco_financials`, `crosswalk` (CERT/CIK/RSSD/ticker), `branches` (SOD); Dagster orchestration; Great Expectations gates; multi-decade backfill.
- **Exit criteria:** one bank's full history reproducible end-to-end; MVP slice loaded; DQ gates green; lineage visible.

### Phase 2 — Gold layer, time-series & market data *(Months 3–4, overlaps Ph1)*
- **Objective:** build the reusable feature contract + the quant/market data.
- **Deliverables:** Gold features (`qoq_delta_*`, `concentration_ratio_*`, `uninsured_deposit_pct`, `funding_stability_score`, `growth_rate_3yr`, `percentile_rank_*`) via **dbt + PySpark**; market-OHLC ingestion → **ClickHouse**; **DuckDB** query layer over Gold; **Feast** feature store; data catalog.
- **Exit criteria:** any Gold column traceable to Bronze; a DuckDB query over Gold returns sub-second; candles queryable from ClickHouse.

### Phase 3 — Deterministic feature services: 11, 12, 14, 16 *(Months 4–6)*
- **Objective:** ship the non-ML / light-ML features early (fast wins).
- **Deliverables:**
  - **F11 X-Ray** — rule-based concentration scoring + peer percentile (service over Gold/DuckDB)
  - **F12 Filing Diff** — z-score change detection vs. each bank's own historical volatility
  - **F14 Peer Clustering** — K-Means/GMM on funding/loan/growth features; silhouette validation; writes `peer_cluster_id` back to Gold
  - **F16 Capital Buffer Simulator** — **Rust engine** (QuantLib for duration/rate shock); pure, **property-tested** deterministic math; Basel-style pass/fail
- **Exit criteria:** all four exposed as gRPC services with tests; F16 has property tests proving ratio math; a thin internal demo UI shows them.

### Phase 4 — ML platform & the showcase model: Feature 13 *(Months 6–8)*
- **Objective:** the defensible, history-validated centerpiece.
- **Deliverables:** MLflow + Feast wired; labeled dataset (SVB/Signature/First Republic/WaMu/IndyMac positives + matched survivors as negatives); XGBoost + logistic baseline; **SHAP** drivers; strict temporal split + leakage audit + calibration; **backtest harness ("would it have flagged SVB in 2022-Q4?") as a CI test**; ONNX serving; model card + drift monitoring.
- **Exit criteria:** backtest demonstrably flags known failures pre-collapse without lookahead; interpretable drivers per prediction; champion model registered and gated by human sign-off.

### Phase 5 — MCP server & tooling *(Months 8–9)*
- **Objective:** one governed API surface for all consumers.
- **Deliverables:** MCP server (Python SDK) exposing all core + quant tools (§7); OIDC + OPA authz; per-call audit; JSON-schema validation; tool versioning; rate limiting; a **CLI/SDK**; the data-license registry enforced at this boundary.
- **Exit criteria:** every feature callable as an audited MCP tool; a scripted chain (`list_banks → get_risk_score → get_bank_xray`) runs green; unauthorized/over-quota calls correctly rejected.

### Phase 6 — Agentic AI layer *(Months 9–11)*
- **Objective:** autonomous analyst copilot on top of MCP.
- **Deliverables:** Supervisor + specialist agents (Risk, Filings, M&A, Macro/Stress) on Claude models; RAG over filing text (pgvector/Qdrant); guardrails, tracing, HITL for side-effects; agent memory; an **eval suite** of analyst questions in CI; the "ask it anything" demo.
- **Exit criteria:** agents answer open-ended questions by chaining tools, cite filing text, pass the eval suite, and never take an unapproved side-effect.

### Phase 7 — Visualization & quant terminal UI *(Months 10–12, overlaps Ph5–6)*
- **Objective:** the dense, real-time quant terminal.
- **Deliverables:** Next.js terminal with candlesticks (Lightweight Charts), market-cap treemap, ratio heatmaps, peer/M&A network graphs, stress waterfall, SHAP plots, percentile bands, yield-curve panels, SOD branch maps (deck.gl), filing-diff view; live WebSocket candles; theming + accessibility.
- **Exit criteria:** every feature has a first-class visualization; real-time price panel updates live; Lighthouse/a11y budgets met.

### Phase 8 — Hardening, security, compliance, SRE & GA *(Months 12–14)*
- **Objective:** production readiness.
- **Deliverables:** external **pen test** + security review; DR/BCP with tested restores; load + chaos testing; SLOs & runbooks; data-quality SLAs; model-governance documentation; performance/cost tuning; full docs; **GA cutover**.
- **Exit criteria:** SLOs met under load; DR restore verified; security findings remediated; sign-off from risk/compliance.

### Phase 9 — Continuous evolution *(post-GA, ongoing)*
- Derivative features (real-time deposit-flight monitoring, sector contagion/network-risk, automated quarterly "what changed" briefings, EU expansion via EBA, cross-bank scenario simulation); scheduled retraining; FinOps; scaling as adoption grows.

**Timeline shape (parallelizable):**
```
Month:      1   2   3   4   5   6   7   8   9  10  11  12  13  14
Ph0 ▣
Ph1     ▣▣▣▣▣▣
Ph2         ▣▣▣▣
Ph3             ▣▣▣▣▣▣▣▣
Ph4                     ▣▣▣▣▣▣▣▣
Ph5                             ▣▣▣▣
Ph6                                 ▣▣▣▣▣▣▣▣
Ph7                             ▣▣▣▣▣▣▣▣▣▣
Ph8                                         ▣▣▣▣▣▣▣▣
Ph9                                                 ▣▣→ ongoing
(Security / DataOps / MLOps / Observability / Governance run across ALL phases)
```

---

## 14. Team & effort

A realistic pod for the enterprise build (roles, not necessarily headcount 1:1):
- **1 Platform/Data Architect** (this plan's owner)
- **2 Data engineers** (ingest/medallion, Rust + Spark/dbt)
- **1–2 ML engineers** (features 13/14, MLOps)
- **1 Backend engineer** (MCP, feature services, gRPC)
- **1 Agent/AI engineer** (agentic layer, evals)
- **2 Frontend engineers** (quant terminal, charting)
- **1 SRE/Platform** (K8s, observability, DR)
- **1 Security/Governance** (part-time; compliance sign-offs)

A solo builder can still traverse the whole plan by descoping the elastic/HA tiers (single-node Postgres/DuckDB/ClickHouse, one small K8s or even docker-compose for dev) while keeping the *architecture* intact — the open formats mean the descoped version upgrades to the full one without a rewrite.

---

## 15. Top risks & mitigations

| Risk | Mitigation |
|---|---|
| **Market-data licensing** blocks redistribution | Data-license registry enforced at MCP/serving boundary; start with open EOD tiers; legal review in Phase 0 |
| **Feature-13 model looks impressive but leaks** | Strict temporal splits, leakage audits, calibration, backtest-as-CI-test, human sign-off gate |
| **Scope sprawl** (six features → fifty) | Gold-layer contract + MCP tools keep marginal-feature cost low; roadmap gates new features to Phase 9 |
| **Over-engineering infra** for non-petabyte data | Deliberately modest cluster; ClickHouse+DuckDB+Postgres instead of a giant Spark farm; scale-to-zero batch |
| **Source schema drift** (FFIEC/FDIC change fields) | Data contracts + DQ gates fail loudly; connectors versioned; MDRM mapping tables |
| **Scraper legal/ToS exposure** | Bulk/API first; robots + rate-limit compliance; identifiable UA; scrape only no-API artifacts |
| **Agent does something unsafe** | Read-only tools by default; HITL for side-effects; tracing + eval suite in CI |

---

## 16. What makes this platform (not just a dashboard)

- **Build Gold once, reuse everywhere** — six features, an MCP surface, and an agent fleet all read the *same* governed feature layer. Marginal feature cost is a query, not a pipeline.
- **Validated against real history** — feature 13's "would it have flagged SVB?" is a CI test, not a slide.
- **Three consumption modes, one backend** — humans (quant terminal), machines (CLI/SDK), and AI agents (MCP) with no duplicated logic and full audit.
- **Enterprise-real** — open formats, sovereign/on-prem-capable, licensed-data governance, model risk management, DR — the things that separate a demo from a system a bank runs for years.

---

## Appendix A — ADRs to write in Phase 0
1. Table format: Iceberg vs. Delta
2. Databricks vs. sovereign OSS lakehouse
3. Language split (this doc §4) ratified
4. ClickHouse vs. TimescaleDB for time-series serving
5. pgvector vs. Qdrant for RAG
6. Kafka vs. Redpanda
7. MCP server language (Python-now vs. Rust-later) and migration trigger
8. Agent framework: Claude Agent SDK vs. LangGraph

## Appendix B — Key source endpoints (verified)
- FDIC BankFind Suite API — `https://banks.data.fdic.gov` / `https://api.fdic.gov/banks/docs/`
- FFIEC CDR Public Data Distribution — `https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx`
- SEC EDGAR APIs — `https://www.sec.gov/search-filings/edgar-application-programming-interfaces` (bulk: `data.sec.gov`, `companyfacts.zip`; 10 req/s)
- Fed NIC FR Y-9C download — `https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload`
- FRED API — `https://fred.stlouisfed.org/docs/api/fred/`
- EBA Transparency/EUCLID — `https://www.eba.europa.eu/eu-wide-transparency-exercise-0`
