# Client Meeting — Requirements Capture

**Attendees (simulated):**
- **The Banker** — commercial/corporate banking MD, or a bank-M&A coverage banker.
  Thinks in franchises, deals, relationships, and board decks.
- **The Banking Analyst** — sell-side or credit analyst covering regional banks.
  Thinks in quarters, estimates, peer sets, and Excel.
- **The Quant** — buy-side risk/systematic. Thinks in distributions, backtests,
  factor exposures, and reproducibility.

Each requirement is tagged with the issue IDs in `03-issue-register.md` that it maps
to, so nothing here is an orphan opinion.

---

## 1. The Banker

> *"Show me the whole banking system, not a slice."*

- The $1B–$250B band excludes JPMorgan, BofA, Citi, Wells — and every community bank
  under $1B. "I cannot take this to a client meeting where the first question is
  'how does this compare to JPM'." → **B3**
- Banks are owned by **holding companies**. Deals happen at HoldCo level, KRE
  constituents are HoldCos, and the analyst consensus is HoldCo. BankLens is
  bank-charter-only. → **B4, D4**

> *"M&A is the reason I would pay for this — and it is half-built."*

- Ranked partners with a rationale sentence is a good start. What is missing is the
  **pro-forma**: combined assets, combined CET1, goodwill created, tangible book value
  dilution, earn-back period, deposit-market-share overlap that would trigger a DOJ/Fed
  divestiture. → **C9**
- "Show me the county HHI *for the combined entity*, and flag which markets would
  breach 1800." The data for this already exists (`county_concentration` + the two
  footprints) — it is simply never combined. → **C9, E8**
- Deal comps: recent completed bank M&A with price/TBV and price/earnings multiples.
  Not in the data model at all. → **B6**

> *"I need to walk out with a document."*

- One-click **PDF tearsheet** per bank, and **Excel/CSV export** of any table.
  This is non-negotiable and there is currently no export anywhere in the product.
  → **D1**
- Board-ready charts: clean, labelled, sourced, printable. The current charts are
  screen-only, with no export-chart-data and no print stylesheet. → **E14, D1**

> *"Say the quiet part out loud."*

- There is no disclaimer anywhere that this is not investment advice, not a
  regulatory capital calculation, and not a supervisory rating. For a product that
  puts "deposit-flight risk 62%" next to a named, real, operating bank, that is a
  legal exposure, not a nicety. → **G7**

---

## 2. The Banking Analyst

> *"Time is the primary axis and your product barely has one."*

- Only `/trends` and `/filing-diff` are time-aware. Every other page — screener,
  earnings, credit, funding, heatmap, treemap, distributions, clusters, geography,
  market share, network, stress lab — is silently locked to the latest quarter with
  no selector. → **D3**
- Only 8 quarters are landed, so `growth_rate_3yr_pct` is *always* `None` and
  `deposit_growth_1yr` is *always* imputed at scoring time. The most important
  early-warning feature in the deposit-flight model is a constant. → **B1**
- FDIC performance ratios are **year-to-date annualised**. The UI says so in one
  caption on the metric-group pages. It should be structural: Q1 vs Q4 is not
  like-for-like and the product should compute or offer a quarterly-isolated view.
  → **C15**

> *"Let me build my own peer group."*

- Behavioural clusters are genuinely novel and I like them. But my coverage universe
  is 14 named banks, and there is no way to define that set, save it, and have every
  page respect it. → **D5**
- The comparison page has a fixed metric list and no charts — it is a table. I want
  arbitrary metrics, and I want them plotted. → **D6**

> *"Where does *this* bank sit?"*

- The distributions page shows the population histogram with a median line. It never
  marks where the bank I care about sits. That is the entire point of a distribution.
  → **E4**
- Percentiles are computed against the whole population. A $1.2B bank ranked against
  a $200B bank is not a peer percentile, it is a size percentile in disguise. I want
  percentiles *within* a size bucket or *within* a cluster. → **C11**

> *"Alerts, or it does not enter my workflow."*

- Watchlist is a bare list of certs. No notes, no threshold alerts ("tell me when
  uninsured deposits move more than 3pp"), no email/notification, no saved screens.
  → **D2**
- The quarterly briefing is genuinely good — but it is a page I have to remember to
  visit, not something that reaches me. → **D2**

> *"Show me the audit trail from the chart back to the filing."*

- If I put "Texas Ratio 41.2%" in a note, my compliance desk will ask which line
  items produced it. There is no drill-down from a Gold metric to the FDIC field
  names and the Bronze checksum, even though the provenance is captured. → **D9, G9**

---

## 3. The Quant

> *"Your headline model is n=4."*

- Four positives (SVB, Signature, First Republic, IndyMac), in-sample AUC 0.955,
  leave-one-out over those same four. There is no k-fold, no held-out period, no
  precision-recall curve, no base-rate adjustment, no calibration, no confidence
  interval on any coefficient. The `risk_score` is rendered as a percentage next to
  a real bank's name, which reads as a probability of failure and is not one.
  → **C1, C2, E13**
- "Structural resemblance" is the honest framing in the docstring and the caveat text
  — but the UI renders `62.4%` in a red bar. The visual overrides the caveat.
  → **C1, E13**

> *"Nothing here has ever been backtested."*

- Not the deposit-flight score, not the X-Ray flags, not the filing-diff z-flags, not
  the M&A fit weights. There is no harness that asks "did a flag at time *t* predict
  anything at *t+k*?" You have 8 quarters of population data — that is enough to build
  the harness even if the answer is "no signal yet". → **C14, C9**

> *"The stress engine is a spreadsheet, not a stress test."*

- Single period, static balance sheet, no PPNR/earnings offset, no management actions.
  A real bank earns its way through a mild shock; this model has no revenue at all.
  → **C4**
- AFS duration is hardcoded at 4 years and HTM at 6 years **for every bank in the
  population**. That is the single largest source of error in the entire rate leg.
  → **C4**
- Parallel shocks only. The SVB story is a steepener/inversion story. No curve twist,
  no key-rate durations. → **C4, C5**
- Loan losses are a flat percentage of gross loans. No segment-level PD/LGD, no CECL,
  no vintage curves — despite the Gold layer already holding a disjoint 8-category
  loan taxonomy that is exactly what you would apply segment loss rates to. → **C6**
- No liquidity metric. No LCR, no NSFR, no survival horizon. The model computes a
  "shortfall forcing HTM sales" and then stops. → **C4**
- No EVE / ΔNII. Interest-rate risk in the banking book *is* the 2023 story and it is
  not modelled. → **C5**
- The three shock legs are independent sliders. Loan losses, deposit outflow and rate
  shocks are correlated in every real crisis. No correlation structure, no Monte Carlo,
  no joint scenario distribution. → **C4, D10**

> *"Give me market-implied risk, not just filed risk."*

- You have EOD OHLCV for the matched tickers and you draw a candlestick. That is
  the least you can do with it. Missing: beta vs KRE/KBE, realised vol vs peers,
  drawdown, price/TBV, price/earnings, and the correlation between filed risk metrics
  and equity underperformance — which would be the first real validation of the
  X-Ray. → **C10, E1, E2**

> *"Reproducibility."*

- Retraining overwrites `ml/deposit_flight/model_card.json` in place. There is no
  version, no hash, no history. A score shown to a user in Q1 cannot be reproduced
  after a Q2 retrain. → **G8**
- No `as_of` query anywhere. FDIC restates. The Bronze layer is append-only and could
  support point-in-time reconstruction; nothing exposes it. → **B9**

---

## 4. What all three asked for independently

These came up from more than one seat and should be treated as the highest-priority
product gaps:

1. **Export — CSV, Excel, PDF.** (Banker, Analyst) → **D1**
2. **A quarter selector on every page.** (Banker, Analyst, Quant) → **D3**
3. **Custom peer sets that persist across the app.** (Banker, Analyst, Quant) → **D5**
4. **Named scenario library, not three raw sliders.** (Banker: "2023 rate path";
   Analyst: "CCAR severely adverse"; Quant: "a joint distribution") → **D10**
5. **Show where *my* bank sits inside every population chart.** (all three)
   → **E4, C11**
6. **Bigger universe — GSIBs at the top, community banks at the bottom, HoldCos in
   between.** (all three) → **B3, B4**
7. **Something that proves the numbers mean anything — a backtest.** (Analyst, Quant)
   → **C14**

---

## 5. What would stop an investor writing a cheque

Ranked by how quickly it would surface in diligence:

| # | Blocker | Issue IDs |
|---|---|---|
| 1 | **There is no live demo.** It cannot be deployed. A hardcoded `localhost` API base means there is literally no URL to send. | A1, A2, A3 |
| 2 | **The flagship model is n=4 and never validated out of sample.** | C1, C2, C14 |
| 3 | **No export, no alerts, no saved state** — it is a viewer, not a workflow tool, so there is no retention story. | D1, D2, D5, D8 |
| 4 | **Universe excludes the banks everyone talks about.** | B3, B4 |
| 5 | **Documentation integrity** — ~11 files referenced in code comments do not exist, including `docs/` entirely and `CHANGELOG.md`. Diligence reads comments. | F2, F20 |
| 6 | **Licensing claim not enforced in code.** `config/sources.yaml` states the serving layer enforces `license.redistributable` at its boundary. No code does. Tiingo data is marked non-redistributable and is served raw. | G3 |
| 7 | **MCP server has no authorization at all** — the agent fleet's only gate is a single REST endpoint tier. | G1, G2 |
| 8 | **Zero frontend tests**; several Python test files referenced in comments and CI narrative do not exist. | F1, F2, F3 |
| 9 | **No disclaimers** on a product that scores named, real, operating banks for run risk. | G7 |
| 10 | **Charts are static and screenshot-grade, not terminal-grade** — no crosshairs, no linked brushing, no drill-down, three inconsistent chart idioms. | E1–E15 |
