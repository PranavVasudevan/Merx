# MERX Frontend — Master Reference Prompt

Use this as context when handing frontend work on BankLens to another agent (e.g. Manus). It
describes exactly what visualization stack is in place, what every page renders and with which
library, and what is explicitly deferred/future work — so a new agent doesn't reinvent, duplicate,
or contradict what's already built.

## 1. What BankLens is

A bank-intelligence "quant terminal" over **real FDIC/SEC/SOD data** for every US bank with
$1B–$250B in assets (~1,049 banks, 2026Q1 slice). Zero paid APIs — every number traces to a real,
free government or SEC source. React 19 SPA talking to a Python REST bridge (`services/api-gateway`)
that wraps an MCP tool server (`services/mcp-server`) over a medallion Bronze→Silver→Gold pipeline.
This document covers **only the frontend** (`frontend/apps/web`).

## 2. Stack

```json
{
  "react": "^19.2.7", "react-dom": "^19.2.7", "react-router-dom": "^7.18.2",
  "recharts": "^3.10.1", "echarts": "^6.1.0", "lightweight-charts": "^5.2.0",
  "motion": "^12.43.0", "oidc-client-ts": "^3.5.0"
}
```
Build: Vite 8 (rolldown), TypeScript strict, `oxlint`. No CSS framework — hand-written tokens in
`theme.css` (light/dark via `prefers-color-scheme` + a manual toggle), consumed as CSS custom
properties everywhere except inside canvas-based charts (SVG/canvas can't resolve `var()`, see §4).

**Three charting libraries, each for a specific job — do not blur these lines:**
- **recharts** — every "plot real numbers against real numbers" chart: line charts, bar charts,
  scatter charts, small-multiples. SVG-based, themeable via CSS vars directly.
- **ECharts** (`echarts/core`, tree-shaken — never import the full `echarts` barrel, it's ~1MB) —
  only for chart types recharts can't do: treemap, heatmap matrix, force-directed graph. Wrapped in
  one hand-written component, `components/EChart.tsx` (~90 lines) — **not** `echarts-for-react`
  (that package's peer range caps at React 18 and double-`init()`s under React 19 StrictMode).
- **lightweight-charts** (TradingView's OSS library) — candlestick price charts only, one component
  (`CandlestickChart.tsx`).
- **Raw `<canvas>`, hand-rolled** — exactly one case: the US branch map, because it needs a real
  cartographic projection no charting library ships (`albers.ts` + `components/BranchMapCanvas.tsx`).

Route-level code-splitting: every page is `React.lazy()`-loaded (`App.tsx`), and each vendor chart
lib is its own build chunk (`vendor-recharts`, `vendor-echarts`, `vendor-lightweight-charts`) so no
visitor downloads a charting library their page doesn't use.

## 3. Design system

- `theme.css` (233 lines) — spacing scale (`--space-1..5`), type scale (`--text-xs..2xl`), radii,
  durations/easing (`--ease-organic`), and two token sets: UI colors (`--surface`, `--border`,
  `--text-primary`, `--status-good/warning/critical`) and **dataviz-specific tokens**: 8 categorical
  colors (`--cat-blue/green/magenta/yellow/aqua/orange/violet/red`), a 4-step sequential ramp
  (`--seq-100/300/450/600`), diverging pos/neg (`--div-pos/neg`), `--gridline`, `--baseline`.
- `colors.ts` — the *only* place that reads those tokens into JS. SVG/canvas can't resolve
  `var(--x)`, so `chartColors()` reads `getComputedStyle(document.documentElement)` at call time and
  returns concrete hex strings (with a hardcoded fallback pair for SSR/no-DOM). `onThemeChange(cb)`
  subscribes to an OS light/dark flip via `matchMedia` so canvas/ECharts charts (which don't
  re-render on their own like recharts does) repaint instead of going stale. `categoricalPalette()`
  and `sequentialRamp()` return ordered arrays from the same tokens. **Everything glass this system:
  never hardcode a hex color in a chart component** — always `chartColors()`.
- `echartsTheme.ts` — `baseEChartTheme()` / `tooltipStyle()` / `axisStyle()`, thin wrappers deriving
  ECharts theme objects from `chartColors()`, so ECharts and recharts always agree visually.
- Motion (`motion/react`) for entrance stagger (`containerVariants`/`itemVariants` pattern repeated
  across every page — see `BankPage.tsx`), tooltip fade-in, and animated bar/track fills.

## 4. Full page inventory (23 routed pages)

Grouped as they appear in the nav (`components/NavShell.tsx`). "Viz" = the actual chart type(s);
"Lib" = which of the four systems in §2 renders it.

### Explore
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/` Overview | Population dashboard: KPI tiles, cluster distribution, risk leaderboard w/ state+cluster filters | animated horizontal bar list (CSS `motion.div` width tween, not a chart lib) | none (hand-rolled) |
| `/screener` | Filter/sort all 1,049 banks incl. ROA/NPL/CET1 columns | sortable data table | none |
| `/compare` | Side-by-side 2–6 banks across 10 metrics | data table | none |

### Analyze
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/earnings` `/credit` `/funding` | Population-wide metric-group tables (shared `MetricGroupPage.tsx`) | sortable table w/ percentile shading | none |
| `/trends` | One bank's full quarter-by-quarter history | 5-panel small-multiple line charts + cluster-label timeline strip | recharts |
| `/filing-diff` | Two-quarter side-by-side, every tracked line item | data table, z-score flagged rows | none |
| `/briefing` | Quarterly "what changed" — churn, movers, cluster migrations, risk entrants | stat tiles + animated transition bars | none (CSS) |

### Visualize
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/heatmap` | Bank × metric percentile matrix | ECharts `heatmap` series | ECharts |
| `/treemap` | Population sized by assets, colored by X-Ray risk, grouped by cluster/state | ECharts `treemap` series | ECharts |
| `/distributions` | Histogram + percentile bands for any Gold metric, with disclosed exclusions | recharts `BarChart` + `ReferenceLine` (median) | recharts |

### Governance
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/clusters` | Silhouette-by-k evidence, cluster centroids, size-vs-behavior mismatch | recharts `BarChart` (silhouette) + data tables | recharts |
| `/model` | Deposit-flight model card, leave-one-out backtest, driver contributions | recharts coefficient table + **beeswarm-style scatter** (one `ScatterChart` per feature, jittered y, split into two color series by contribution sign) | recharts |

### Geography
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/geography` | All 75K+ real bank branches on a US map | **hand-rolled canvas** — real Albers Equal-Area Conic projection (`albers.ts`, Snyder's formula, USGS standard parallels), density via low-alpha overlapping dots, custom hit-testing for hover tooltips | raw `<canvas>` |
| `/market-share` | County-level deposit HHI vs Fed merger-review thresholds | expandable data table (no chart — deliberately; see §6) | none |

### Simulate
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/network` | M&A-fit force graph, largest banks + top partners | ECharts `graph` series, force layout, categorical coloring by behavioral cluster | ECharts |
| `/stress-lab` | Cross-bank scenario testing (cluster/watchlist/top-N) + linear-vs-QuantLib pricing comparison | ranked list w/ pass/fail dots + before→after values | none (CSS) |

### Research
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/filings` | Semantic search over real SEC 10-K risk-factor text (pgvector RAG) | search results list w/ similarity score, quoted source text | none |

### My work / Tools
| Route | Purpose | Viz | Lib |
|---|---|---|---|
| `/watchlist` | Tracked banks w/ live risk score + X-ray flags | animated risk-zone bars | none (CSS) |
| `/assistant` | Chat with a persona-routed agent over the MCP tool fleet | chat transcript | none |
| `/activity` | Agent-run + MCP audit log | data table | none |
| `/bank/:cert` | **The core per-bank dashboard** — composes ~10 panels (see §5) | mixed — see below | mixed |

## 5. Reusable per-bank visualization components (all live on `/bank/:cert`)

| Component | Viz | Lib |
|---|---|---|
| `KpiTiles.tsx` | 6 stat tiles (assets, uninsured %, CRE %, CET1, peer cluster, branch network) | none |
| `CandlestickChart.tsx` | OHLCV price chart | **lightweight-charts** |
| `XrayPanel.tsx` | Concentration/structural risk flags w/ peer-percentile bars | CSS `motion.div` bars |
| `ConcentrationChart.tsx` | Loan mix (CRE/C&I/Residential/Consumer/Ag) w/ peer percentile tooltip | recharts |
| `CapitalChart.tsx` | CET1/Tier1/Total/Leverage vs regulatory minimum | recharts `BarChart` (horizontal) |
| `FilingDiffPanel.tsx` | Top flagged line-item changes (links to full `/filing-diff`) | data rows |
| `PeerClusterCard.tsx` | Behavioral cluster + sample peers | text card |
| `RiskScorePanel.tsx` | Deposit-flight score + driver bars | recharts |
| `MaFitPanel.tsx` | Ranked M&A candidates w/ fit score bar + **real geo-overlap %** (branch-network overlap from landed SOD footprints) | CSS bars |
| `StressPanel.tsx` | Single-bank stress simulator w/ sliders, capital waterfall | recharts `BarChart` (waterfall via stacked transparent+visible bars) |
| `PeerScatter.tsx` | This bank vs ~1,037 peers, CRE% vs Uninsured% | recharts `ScatterChart` |

## 6. Deliberate non-visualizations (read before "fixing" these)

- **`/market-share` has no map.** The plan originally called for a "county choropleth." Real county
  *boundary polygon* data isn't landed anywhere in this repo and fetching it would violate the $0/
  no-network-dependency constraint on `/geography`'s canvas. Shipped as a sortable/expandable table
  instead of fabricating a fake-looking bubble map. **If choropleth is wanted later, it needs a real
  TopoJSON/GeoJSON county boundary file landed to Bronze first** — do not approximate with circles
  sized by centroid, that was rejected as visually implying precision the data doesn't have.
- **`/geography` excludes Alaska, Hawaii, and territories** (~0.9% of branches), not silently — the
  page displays the exact excluded count. A true "Albers USA" projection insets AK/HI into the same
  canvas (what D3's `geoAlbersUsa` does); that requires per-region affine transforms this build
  doesn't implement. If asked to add the inset, the projection math is additive on top of `albers.ts`,
  not a rewrite.
- **Screener/Compare/Overview leaderboard tables are plain HTML tables, not chart-library grids.**
  This is deliberate — sortable/filterable tabular data with 200+ rows renders faster and is more
  scannable as a real `<table>` than as a chart-library "table" component.

## 7. What is NOT built yet — real future work, not hypothetical

In priority order, each already scoped in `docs/architecture/BankLens-Master-Architecture-Plan.md`:

1. **FRED macro/yield-curve integration** — free, keyless, no-cost. `/stress-lab`'s `rate_shock_bps`
   slider currently has no anchor to a real rate environment; FRED would let a shock be framed as
   "if rates repeat 2022's move" instead of an arbitrary bps number. Needs: a new Bronze connector
   (`sources/fred.py`, same shape as `sources/sec.py`), a small line chart on `/stress-lab` showing
   the anchor rate path (recharts, same pattern as `/trends`).
2. **County choropleth for `/market-share`** — see §6. Needs a real boundary file landed first.
3. **Tiingo-gated market data lighting up** — `CandlestickChart`/`get_price_candles` and
   `get_market_snapshot` already have real, tested code paths; they're just empty for any bank
   without a landed ticker (crosswalk match) because `scripts/land_market_data.ps1` needs the user's
   own free Tiingo key. No frontend work needed — this "activates" existing UI once the key is
   supplied and the script is run.
4. **EBA/EU bank expansion** — a second regulatory domain (119 EU banks, different schema/filing
   structure entirely). Would need new pages, not just new data — worth its own scoping pass, not an
   incremental addition to existing pages.
5. **Wider `/filings` coverage** — pgvector RAG search is fully built and live (10 real filers
   landed as of last run, `scripts/land_filings.ps1 -Limit N` re-run to extend). Frontend needs
   nothing new; more landed filers just means richer search results. If corpus grows past ~10K
   chunks, `libs/python/banklens_common/db.py`'s `search_filing_chunks()` currently does exact
   brute-force cosine search (deliberately, see its docstring) — an HNSW/IVFFlat index would need
   real tuning at that point, not before.
6. **`/contagion` — explicitly cut, not deferred.** No counterparty/interbank/repo data exists or is
   free (would need FR Y-15). Do not build a "contagion" page from branch-overlap or loan-mix
   similarity — that was rejected as a fabricated causal claim dressed in real inputs. The honest
   version of this idea already lives on `/network` (M&A fit) and `/market-share` (deposit
   concentration) under accurate labels.

## 8. Conventions to preserve if extending this frontend

- **No mock data, ever.** Every number renders from a real MCP tool → REST route → Gold field. If a
  metric can't be computed from real landed data, the UI shows an explicit empty/error state with a
  reason (see `/filings`' coverage banner, `/geography`'s excluded-branch count) — never a
  placeholder number.
- **Disclose exclusions and scope limits on the page itself**, not just in a code comment — e.g.
  `/distributions` names which banks were excluded from a deposit-based metric and why;
  `/filings` states exactly how many filers are searchable.
- **New page checklist**: MCP tool in `services/mcp-server/src/banklens_mcp/tools.py` → REST route in
  `services/api-gateway/src/bridge_server.py`'s `ROUTE_TIERS` + `ROUTES` → matching entry in
  `platform/auth/opa/policy.rego` (`services/api-gateway/tests/test_route_policy.py` fails the build
  if these three drift) → `types.ts` + `api.ts` → page + lazy import in `App.tsx` → nav link in
  `NavShell.tsx`.
- **Pick the chart library by task, not preference**: real x/y numeric data → recharts;
  treemap/heatmap/graph → ECharts (`components/EChart.tsx`, register only the ECharts modules you
  use in that file's `echarts.use([...])` call); OHLCV → lightweight-charts; anything needing a
  projection/custom geometry no library provides → raw canvas, following `albers.ts`'s pattern of
  pure functions + a `fitAlbers()`-style bounds-fitting helper.
- **Every chart reads colors from `chartColors()`**, subscribes to `onThemeChange()` if it's
  canvas/ECharts (not needed for recharts, which re-renders with fresh CSS var reads automatically).
