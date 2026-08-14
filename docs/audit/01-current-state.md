# BankLens — Current State Review

**Reviewed:** 2026-08-12 · commit `dd0afe3` · branch `main`
**Reviewer framing:** senior systems/architecture review, ground-up.

---

## 1. What the project is, and what it is actually trying to be

BankLens is a **bank-intelligence platform built entirely on public regulatory
filings**. The founding constraint — stated in the README and visible everywhere in
the code — is *"every number traces to a real public source; there is no synthetic
data anywhere."* The second founding constraint is a **hard $0 spend rule**
(`.env.example`: `BANKLENS_LLM_PROVIDER=ollama` — "only change this if you
deliberately want to spend money").

Those two constraints explain almost every architectural decision in the repo, both
the good ones and the ones that now hold it back.

The product thesis is: *the raw data regulators publish already contains the answers
analysts pay vendors (S&P Capital IQ, Moody's, Bloomberg BANK<GO>) six figures a year
for — it is just never derived, joined, or visualised.* BankLens derives it once, in
a Gold layer, and every consumer (CLI, MCP tools, REST bridge, web app, AI agents)
reads that one layer.

That thesis is sound. The execution is unusually disciplined for a project of this
size. The gaps are real and are enumerated in `03-issue-register.md`.

---

## 2. The seven features — intent, implementation, and honest state

| # | Feature | Analyst question it answers | Where it lives | State |
|---|---|---|---|---|
| 11 | **Balance-Sheet X-Ray** | Does this bank have concentration risk its headline capital ratio hides? | `transforms/xray.py` | Solid. Rule-based, auditable, 8 supervisory-informed rules, capital-regime aware. |
| 12 | **Filing Diff** | What moved materially between two quarters, judged against *this bank's own* volatility? | `transforms/filing_diff.py` | Works. Z-scores are thin (≤8 observations). |
| 13 | **Deposit-Flight Early Warning** | How closely does this bank resemble real failures? | `transforms/deposit_flight.py`, `ml/deposit_flight/model_card.json` | Works, but n=4 positives. Statistically the weakest claim in the product. |
| 14 | **Peer Group Redefiner** | Which banks does this one actually *behave* like? | `transforms/clustering.py` | Works. k=7 fixed for stable IDs; diagnostics honestly expose that k=4 may score better. |
| 15 | **M&A Fit Finder** | Who are the plausible acquisition partners? | `transforms/ma_fit.py`, `footprint.py` | Works. Real FDIC branch-level geography. Weights are hand-set and unvalidated. |
| 16 | **Capital Buffer Simulator** | What happens to capital under a shock? | `transforms/stress.py`, `quantlib_pricing.py`, Rust port | Works, single-period, static balance sheet. |
| 17 | **Filing risk-factor RAG** | What do 10-Ks actually say about a risk? | `banklens_common/embeddings.py`, pgvector | Works, coverage is a handful of filers. |

### Design decisions worth calling out as *strengths*

These are the things a technical investor or a hiring architect would score highly:

1. **Medallion architecture actually enforced.** Bronze is append-only raw bytes with
   provenance (`_provenance.json` per partition: source URL, timestamp, checksum).
   Silver is one normalised schema for both US (FDIC) and EU (EBA). Gold is computed
   once. *Every* feature reads Gold. There is no place where two consumers derive the
   same number differently.
2. **The loan taxonomy bug fix is genuinely good engineering.** `gold.py`'s
   `LOAN_CATEGORIES` comment documents an earlier version that double-counted parents
   and children and summed to 129.9% of Wells Fargo's loan book. The current 8-leaf
   disjoint set sums to a median 98.7%. That was verified empirically against all
   1,038 banks, not assumed.
3. **Data-quality exclusions are disclosed, not swallowed.** `data_quality.py` +
   `get_metric_distribution`'s `exclusions` block names every institution dropped and
   why. The X-Ray reports `rules_evaluated` / `rules_not_evaluated` / `fully_assessed`
   so "low risk from 2 of 9 rules" cannot be read as a clean bill of health. The stress
   test reports `legs_not_applied` so an EU bank with no disclosed deposits does not
   silently look immune to a deposit run.
4. **Capital-regime awareness.** 195 CBLR electers and 13 foreign-bank branches report
   zero risk-based ratios *because the regulation deems them compliant*. Reading those
   zeros as thin capital was producing a false "CET1 below Basel minimum" flag on 208
   of 1,049 banks. `data_quality.capital_basis` fixes this. Very few projects at this
   level get that right.
5. **Honest negative results.** The deposit-flight docstring says outright that IndyMac
   is a different failure archetype the feature set is not tuned to catch, and that
   Washington Mutual is excluded (assets ~$307B, 10–60× every other training example).
   The cluster diagnostics page renders silhouette-by-k *including the k that beats
   the served k*.
6. **A verified Rust port of the stress engine**, byte-for-byte matched against the
   Python reference, plus proptest property tests.
7. **Real auth, not decorative.** Keycloak OIDC with JWKS signature verification +
   OPA policy evaluation, failing *closed* (503) when either is unreachable — and the
   code explicitly contrasts this with the Postgres path, which fails *open* because
   losing an audit row is low-stakes and losing an auth gate is not.
8. **Route/policy drift is a known hazard and is documented.** `bridge_server.py`'s
   `ROUTE_TIERS` exists specifically because four parallel lists (bridge, `policy.rego`,
   `api.ts`, `NavShell.tsx`) already broke a whole page once when OPA denied by default
   and the frontend's `Promise.all` rejected all-or-nothing on a single 403.

### Design decisions that are *liabilities*

1. **Dependency-free Python was a virtue that is now a ceiling.** Hand-rolled logistic
   regression, hand-rolled k-means, hand-rolled percentile ranks, hand-rolled Albers
   projection. Auditable, yes. But it means no cross-validation, no calibration, no
   scipy statistics, and O(n²) hot paths that are fine at 1,049 banks and break at
   4,500.
2. **The filesystem is the database.** `data/` is 59 MB of Bronze JSON + a 37 MB SOD
   file, mounted read-only into the bridge container. There is no query layer over it
   except an in-memory DuckDB table rebuilt from an NDJSON round-trip at startup.
3. **Everything is pinned to `localhost`.** The frontend's API base, the CORS
   allowlist, and the Keycloak URL default. The web Dockerfile itself admits this
   ("would need to become configurable... for any real non-localhost deployment").

---

## 3. How the frontend talks to the backend

```
FDIC/SEC/EBA/ECB/Tiingo
        │  (stdlib-only Python connectors, provenance + checksum per fetch)
        ▼
   data/bronze/  ──► silver.py / silver_eba.py ──► gold.py ──► peers.py ──► clustering.py
                                                        │
                                   banklens_mcp/data.py │ (loads, computes, caches in a module dict)
                                                        ▼
                        ┌───────────────────────────────┴────────────────────────────┐
                        ▼                                                            ▼
            banklens_mcp/tools.py (27 MCP tools)                        (same functions, no duplication)
                        │                                                            │
          JSON-RPC/stdio│                                                       REST │ bridge_server.py :8791
                        ▼                                                            ▼
             services/agents (4 personas + supervisor)              frontend/apps/web (React 19 + Vite 8)
```

**Key property:** the REST bridge is a *thin* wrapper. Each route is a one-line lambda
over `tools.<fn>`. There is zero business logic in the HTTP layer. The MCP server and
the web app are guaranteed to see the same numbers because they call the same function.

**Auth flow:** `oidc-client-ts` (Authorization Code + PKCE) → Keycloak → access token
in `sessionStorage` → `Authorization: Bearer` on every `api.ts` call → bridge verifies
signature against Keycloak JWKS → extracts `realm_access.roles` → asks OPA whether
those roles may perform this method on this path. Roles are read from the **access**
token, not the ID token — a real bug that was found live and fixed, since Keycloak's
default mapper only puts `realm_access` in the access token.

**Data-shape contract:** `frontend/apps/web/src/types.ts` (676 lines) is the largest
file in the frontend and hand-mirrors every tool's return shape. It is not generated.

### Visualisation stack — what renders what

| Library | Used for | Pages |
|---|---|---|
| **Recharts** (SVG) | Bar charts, line charts, histograms | Bank capital/concentration/risk/stress panels, `/trends`, `/distributions`, `/clusters` |
| **Apache ECharts** (Canvas) | Heatmap, treemap, force graph | `/heatmap`, `/treemap`, `/network` |
| **lightweight-charts** (Canvas) | OHLC candlesticks | Bank page price chart |
| **Hand-rolled Canvas + Albers** | Branch geography | `/geography` (`albers.ts`, `BranchMapCanvas.tsx`) |
| **motion** | Entrance/stagger animation everywhere | All pages |

**The colour system is the best part of the frontend.** `colors.ts` reads the *actual
computed CSS custom properties* off `:root` at runtime rather than maintaining a hex
duplicate of `theme.css`. Both Recharts (which cannot resolve `var()` in SVG
presentation attributes) and the ECharts canvas theme derive from that one source, and
`onThemeChange()` forces imperative canvas charts to rebuild on OS-theme or skin flips.
There is also a "terminal" skin (`skin-terminal.css`) for a Bloomberg-ish look.

**The chart-caption discipline is also strong.** Nearly every chart carries a caption
that says what the data is *not*: the heatmap says percentile colour is neutral, not
good/bad; `/trends` warns that clusters are recomputed independently each quarter so a
label change is not a tracked migration; the treemap says EU banks land in
"Unclassified" under cluster/state grouping.

### Where the frontend/backend seam is weak

- `const BASE = 'http://localhost:8791/api'` — hardcoded, not an env var.
- Every page fetches on mount with `Promise.all`; one 403 or one slow route kills the
  whole view. This has already caused a production-shaped outage once (the `/ma-fit`
  OPA tier issue documented in `policy.rego`).
- No caching layer, no `ETag`, no `stale-while-revalidate`. `/api/population` ships the
  entire population on every visit to Overview, Screener, and Stress Lab.
- Almost no page state lives in the URL, so views are not shareable.
- No error boundary; a render-time throw blanks the app.

---

## 4. Current effectiveness — an honest score

**What actually works today, end to end, with real data:**

- 1,049 US banks × 8 quarters (2024Q2 → 2026Q1) + 120 EU significant institutions.
- 76,120 real branch locations across 4,431 certs, with real county HHI against the
  Fed's own 1800 bank-merger screening threshold.
- 27 MCP tools, 33 REST routes, 23 routed frontend pages, all reading one Gold layer.
- Real OIDC + OPA, real Prometheus metrics, real Grafana dashboard, real K8s manifests
  with dev/staging/prod overlays and a quarterly refresh CronJob.
- CI that blocks on ruff, runs the Python suite against a real Postgres service,
  clippy+test on two Rust crates, frontend typecheck+build, Docker builds, and
  `kubectl kustomize` validation.

**Scorecard:**

| Dimension | Score | Why |
|---|---|---|
| Data integrity & lineage | **9/10** | Provenance, checksums, disclosed exclusions, no synthetic data. Best-in-class for a project this size. |
| Architectural discipline | **8.5/10** | "Build Gold once" is genuinely enforced. Thin bridge. No duplicated logic. |
| Analytical depth | **5/10** | Ratios and rules are excellent. Models are toy-scale. Nothing a quant would call a model. |
| Visualisation | **6/10** | Correct, honest, well-themed — but static, non-interactive, and missing every chart type the target users would ask for first. |
| Deployability | **3/10** | Runs beautifully on the author's laptop. Cannot be deployed anywhere as-is. |
| Free-tier fit | **2/10** | Ollama, Keycloak, pgvector Postgres, 96 MB of file-backed data, and an in-memory 76k-row load do not fit any free tier. |
| Test coverage | **4/10** | 7 Python test files for ~75 modules. Zero frontend tests. Several referenced test files do not exist. |
| Documentation integrity | **3/10** | Code comments reference ~11 files that are not in the repo, including `docs/` in its entirety and `CHANGELOG.md`. |
| Security posture | **6.5/10** | Real auth done properly at the bridge. MCP server has none. License enforcement is claimed but absent. |

**Overall: a very strong data-engineering and product-thinking project with a shallow
quantitative core and no deployment story.** It would impress an engineering
interviewer and would not survive a quant's second question or a banker's first
request for an Excel export.

---

## 5. Free-deploy reality check

The stated constraint is *free to deploy and free to run*. Here is what actually
blocks that today:

| Component | Free-tier reality |
|---|---|
| **Frontend (Vite/React static)** | ✅ Free forever on Cloudflare Pages / Netlify / GitHub Pages. Blocked only by the hardcoded API base URL. |
| **REST bridge** | ⚠️ `http.server.ThreadingHTTPServer` is not a production server. Fly.io/Render free tiers can run it, but it needs the 96 MB `data/` directory and ~500 MB–1 GB RAM once SOD and 8 quarters are loaded. Render free = 512 MB. **Currently over budget.** |
| **`data/` (96 MB JSON)** | ❌ Free hosts have ephemeral disks. Needs to become a Parquet/DuckDB file in free object storage (Cloudflare R2 free tier = 10 GB) or be baked into the image. |
| **Postgres + pgvector** | ⚠️ Neon and Supabase both have free tiers with pgvector. Not wired — the code only reads `POSTGRES_*` env vars with no connection-string/SSL support. |
| **Keycloak** | ❌ No free always-on host. A Keycloak container is ~600 MB RAM idle. Realistic free alternatives: Auth0 free (7,500 MAU), Clerk free, Supabase Auth, or GitHub OAuth. |
| **OPA** | ⚠️ Could be replaced by in-process `opa-wasm` or a small policy evaluator, removing a whole container. |
| **Ollama (assistant)** | ❌ Impossible on free hosting — needs GBs of weights and CPU/GPU. Gemini free tier (`gemini_keys.py` already implements 5-key rotation) is the only viable path, and it is already coded. |
| **ClickHouse / MinIO / Redis** | ❌ In `docker-compose.dev.yml`, **not referenced by a single line of application code.** Pure dead weight. |
| **Prometheus + Grafana** | ⚠️ Grafana Cloud free tier exists (10k series). Self-hosting both on a free tier is not viable. |
| **Tiingo** | ⚠️ Free tier is 250 calls/day, 50 symbols/hour. Fine, but no code paces against that budget. |

**The realistic free architecture** (see prompts A1–A12) is:
static frontend on Cloudflare Pages → bridge on Fly.io free VM (or Cloudflare Workers
if rewritten) → Gold layer as a single DuckDB/Parquet file → Neon free Postgres for
watchlist/audit/pgvector → Auth0/Clerk free for identity → Gemini free tier for the
assistant. Every one of those is a real change, and every one has a prompt in
`04-remediation-prompts.md`.
