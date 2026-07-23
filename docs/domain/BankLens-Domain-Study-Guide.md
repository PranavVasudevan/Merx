# BankLens — Domain Study Guide & Getting Started

**How to use this:** don't try to read it all first. Learn in the order the build needs it. Each tier says *which BankLens feature it unlocks* so the reading is motivated, not abstract. Tiers 0–2 are the true critical path — everything else you can pick up as you reach that phase.

Priority key: 🔴 essential before you build · 🟡 needed by mid-project · 🟢 deepen later

---

## Tier 0 — Accounting & "what a bank actually is" 🔴
*Unlocks: literally everything. Every field in the Silver `bank_financials` table is one of these concepts.*

- **The balance sheet identity:** Assets = Liabilities + Equity. For a bank, deposits are *liabilities* (money it owes you), loans are *assets* (money owed to it). This inversion trips up everyone at first.
- **What a bank is:** a **maturity-transformation machine** — it borrows short (deposits you can withdraw anytime) and lends long (30-year mortgages). That mismatch is the source of *both* its profit and its fragility.
- **Net interest margin (NIM):** interest earned on loans − interest paid on deposits. This is the core profit engine.
- **The actual asset/liability line items** (these ARE your Silver columns):
  - Assets: loans by type (**CRE** = commercial real estate, **C&I** = commercial & industrial, consumer, residential mortgage, agricultural), and **securities** split into **AFS** (available-for-sale, marked to market) vs **HTM** (held-to-maturity, held at cost — *this distinction is central to the SVB story*).
  - Liabilities/funding: deposits (**insured vs uninsured** — the $250k FDIC line), **brokered deposits**, **FHLB advances**, short-term borrowings/repo.
  - Equity: the capital cushion that absorbs losses.
- **Income statement basics:** net interest income, non-interest income (fees), **provision for loan losses**, ROA, ROE, efficiency ratio.

**Read:** Khan Academy (accounting + banking basics, free) → Investopedia entries for each term above → Mishkin, *The Economics of Money, Banking, and Financial Markets* (the standard textbook — skim the banking chapters, don't read cover to cover).

---

## Tier 1 — Banking risk & capital 🔴
*Unlocks: Feature 11 (X-Ray), Feature 16 (Capital Buffer Simulator), and the whole "risk" framing.*

- **Capital & why it matters:** capital = the equity buffer that absorbs losses before depositors do. A bank fails when losses exceed capital.
  - **CET1 ratio, Tier 1 ratio, leverage ratio** — what each measures and how they differ.
  - **Risk-weighted assets (RWA):** why $1 of Treasuries and $1 of a risky loan don't count the same against capital.
  - **Basel III** — the international framework that defines these minimums. You only need the intuition, not the full 400-page text.
- **The four core risks** (know them cold — they're your feature vocabulary):
  1. **Credit risk** — borrowers default (drives concentration analysis).
  2. **Liquidity risk** — can't meet withdrawals even if solvent (**LCR**, **NSFR**).
  3. **Interest-rate risk (IRRBB)** — rates rise, your long bonds lose value (the SVB killer).
  4. **Market risk** — trading positions move against you.
- **Solvency ≠ liquidity.** A bank can be "solvent on paper" and still die from a liquidity run. Understanding this one sentence is 50% of Feature 13.
- **Concentration risk:** headline ratios look fine, but 40% of loans in one sector, or one depositor class, is a hidden landmine. (This IS Feature 11.)
- **Stress testing:** how regulators shock a balance sheet (**CCAR / DFAST**) — the conceptual model behind Feature 16.

**Read:** Admati & Hellwig, *The Bankers' New Clothes* (the best plain-English book on bank capital — read this one properly) → van Greuning & Bratanovic, *Analyzing and Managing Banking Risk* (World Bank, reference) → BIS/Basel Committee summary docs at bis.org for the ratio definitions.

---

## Tier 2 — Bank runs & the case studies 🔴
*Unlocks: Feature 13 (Deposit Flight — your showcase). This is the emotional and technical core of the project.*

- **The classic theory:** Diamond & Dybvig (1983), *Bank Runs, Deposit Insurance, and Liquidity* — the Nobel-winning model of why runs are self-fulfilling. Read the intuition, not the math, first.
- **Why uninsured deposits are "flighty":** insured depositors (<$250k) have no reason to run; uninsured ones (corporations, VCs) flee at the first rumor. Uninsured-deposit % is the single most important Feature-13 variable.
- **The modern digital run:** SVB lost ~$42B in a *day* in March 2023 — Twitter + mobile banking made runs faster than ever. The old models assume slow queues at branches; reality is now instant.
- **The case studies (your labeled training data):**
  - **SVB (2023)** — HTM bond losses from rate hikes + concentrated uninsured tech deposits + no rate hedging. The textbook case.
  - **Signature Bank (2023)** — crypto-concentrated deposits.
  - **First Republic (2023)** — uninsured wealthy clients + underwater mortgages.
  - **Washington Mutual (2008)** — mortgage credit losses, largest bank failure in US history.
  - **IndyMac (2008)** — early run, good contrast case.

**Read (do this — it's the most valuable single item):** the Federal Reserve's *Review of the Supervision and Regulation of Silicon Valley Bank* (the "Barr Report," April 2023) — a free, superb, plain-English autopsy of exactly the signals your model tries to catch. → Matt Levine's *Money Stuff* archives on SVB (Bloomberg) for the best intuition-building writing in finance.

---

## Tier 3 — Markets, valuation & the quant layer 🟡
*Unlocks: the visualization terminal (candles, market-cap tiles) and Feature 15 (M&A).*

- **Equity market basics:** market cap, shares outstanding, **P/B (price-to-book)** — *the* ratio for banks (they trade relative to book value; a bank at 0.5× book is the market screaming distress), P/E, ROE.
- **Bank valuation specifically:** why banks are valued differently from normal companies (book value, ROE, cost of equity). Aswath Damodaran (NYU Stern, free "Damodaran Online") has dedicated bank-valuation material — excellent.
- **Price data mechanics:** OHLC (open/high/low/close), volume, candlesticks, volatility. Enough to know what your candle charts are showing.
- **The yield curve & rates:** how the Fed sets rates, what the Treasury curve is, and *why rising rates crush bank bond portfolios* (ties straight back to SVB). FRED is where you'll pull this.
- **M&A logic:** what makes two banks a good merger fit — complementary funding, loan-book overlap, geographic footprint (Feature 15).

**Read:** Damodaran Online (bank valuation lectures/spreadsheets, free) → Investopedia (candlesticks, yield curve, P/B) → FRED blog for macro intuition.

---

## Tier 4 — Data science / ML for this domain 🟡
*Unlocks: Feature 13 (classifier) and Feature 14 (clustering) — and keeps you honest.*

- **Supervised classification:** logistic regression (baseline) → **XGBoost** (the workhorse). Understand precision/recall/ROC — accuracy is a trap on imbalanced data (few banks fail).
- **Interpretability:** **SHAP values** — how to explain *why* the model flagged a bank. Non-negotiable in banking; a black box won't fly with regulators or in a demo.
- **Unsupervised clustering:** K-Means / Gaussian Mixture, **silhouette score** (Feature 14).
- **Change/anomaly detection:** z-scores vs a bank's *own* history (Feature 12).
- **The traps that make or break Feature 13:**
  - **Data leakage** — using post-failure data to "predict" failure. Fatal and easy to do accidentally.
  - **Temporal validation** — train only on data that existed *before* the prediction date.
  - **Calibration** — a "70% risk" should mean it happens ~70% of the time.

**Read:** *An Introduction to Statistical Learning* (ISLR — free PDF, the standard, read ch. 4 classification, 10/12 clustering) → Christoph Molnar's *Interpretable Machine Learning* (free online, the SHAP chapter).

---

## Tier 5 — Data engineering & platform 🟡
*Unlocks: the whole pipeline (Phases 1–2).*

- **Medallion architecture:** Bronze (raw) → Silver (clean) → Gold (features). Why each layer exists.
- **Lakehouse & table formats:** what Parquet, Iceberg/Delta, and object storage are, and why they beat dumping everything in Postgres.
- **ETL vs ELT, orchestration, data quality, lineage.**
- **OLTP vs OLAP:** why you use Postgres for one job and ClickHouse/DuckDB for another (this is the DB-choice reasoning from the plan).
- **XBRL & regulatory data formats:** the tagged format SEC/FFIEC filings come in.

**Read:** Reis & Housley, *Fundamentals of Data Engineering* (the best single book here) → Kleppmann, *Designing Data-Intensive Applications* (deeper, for later) → the FFIEC **UBPR User's Guide** (free — teaches you the exact ratios regulators compute, which you'll reproduce in Gold).

---

## Tier 6 — MCP & agentic AI 🟢
*Unlocks: Phases 5–6.*

- **Tool/function calling:** how an LLM calls a typed function and uses the result.
- **MCP (Model Context Protocol):** the open standard for exposing tools to AI — read the official spec/docs at modelcontextprotocol.io.
- **Agentic patterns:** supervisor/specialist agents, RAG (retrieval-augmented generation) over filing text, guardrails and human-in-the-loop.

**Read:** the official MCP documentation → Anthropic's guides on tool use and building agents.

---

## Tier 7 — Fintech & regulatory big picture 🟢
*Context that makes you sound like you know the industry.*

- **Who regulates whom:** the Fed, OCC, FDIC, CFPB, and (EU) the EBA/ECB. What each does.
- **The regulatory reports** you're ingesting: Call Reports (FFIEC 031/041), FR Y-9C (holding companies), UBPR (peer analysis).
- **RegTech / SupTech:** how the industry uses data for supervision and compliance.
- **Market-data economics & licensing:** why FDIC data is free to redistribute but Bloomberg/Polygon price data is not.

**Read:** FDIC's *Quarterly Banking Profile* (see the whole US industry at a glance) → Federal Reserve "In Plain English" educational series → skim regulator "about" pages.

---

## The minimal critical path (if you're impatient)

If you read only four things before starting to build:
1. **The balance-sheet inversion** (Tier 0) — deposits are liabilities, loans are assets.
2. **Solvency vs liquidity + capital ratios** (Tier 1) — Admati & Hellwig.
3. **The Barr Report on SVB** (Tier 2) — the single best grounding document.
4. **The FFIEC UBPR User's Guide** (Tier 5) — the exact ratios you'll rebuild.

Everything else you learn *as you reach that phase*.

---

## Where the build actually starts — Phase 0 + a "vertical slice"

The mistake would be to build the whole platform before understanding the data. So the first move is a **thin vertical slice through ONE real bank** — it's simultaneously your first code *and* your best domain lesson.

**Week 1–2 concretely:**
1. **Repo + environment** — set up the monorepo, pick your first language runtime (Python is the fastest way to explore data), basic CI. Keep infra minimal for now (no Kubernetes yet — that comes later).
2. **Pull one real bank from the FDIC BankFind API** — e.g., look up a bank by name, get its `financials` for the last few quarters. No auth needed. *You now have real data in front of you.*
3. **Map the fields to the concepts you just read** — find `total_assets`, `total_deposits`, the loan categories, the capital ratios in the actual JSON. This is where Tier 0/1 becomes real.
4. **Reproduce 2–3 Gold metrics by hand** — compute `uninsured_deposit_pct`, a concentration ratio, and a QoQ delta yourself, and check them against UBPR. When your number matches the regulator's, you understand both the data and the feature.
5. **Then scale** — once one bank works end to end, widen to the MVP slice (US banks $1B–$250B).

That's the exact "get one bank working before scaling" principle from the plan — and it doubles as the most effective way to learn the domain.
