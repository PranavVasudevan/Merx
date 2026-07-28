# BankLens Quant Terminal (Phase 7 reference)

A real-data dashboard over all 6 BankLens features — React + TypeScript + Vite,
charts via Recharts, styled with the validated dataviz palette (light/dark), plus
real candlesticks via TradingView's `lightweight-charts` (Phase 2a).

**Honest scope note on the candlestick chart:** it renders **real** Tiingo EOD data,
never mock candles — but that data needs the user's own free `TIINGO_API_KEY`
(`scripts/land_market_data.ps1`), the one BankLens source that isn't keyless. Until
that's run, the chart shows an honest "no data landed yet" message instead of a
placeholder or fake series. Rendering itself was verified with a temporary mocked
fetch response (see `docs/data-contracts/market_prices.md`) — the component code
path is proven; only the live data pull needs the user's key.

## Run it

Two processes: the REST bridge (Python, wraps the same tool logic as the MCP server)
and the Vite dev server.

```powershell
powershell -File ../../../scripts/dev_web.ps1
```

or manually, in two terminals:
```powershell
powershell -File scripts/api_bridge.ps1      # http://localhost:8791
cd frontend/apps/web && npm run dev          # http://localhost:5173
```

## What's on the page

Search any bank (or start with the default, Dime Community Bank) to see:

- **KPI tiles** — assets, uninsured deposits, CRE concentration, CET1, behavioral cluster
- **Price chart** — real EOD candlesticks + 1d change / 30d volatility / 52-week range, for banks with an exact/high-confidence crosswalk ticker match and landed Tiingo data
- **F11 X-Ray** — severity-flagged structural risks with peer-percentile bars
- **Loan composition** & **capital adequacy** charts (real concentration ratios / regulatory ratios)
- **F12 Filing Diff** — bank-relative z-scored quarter-over-quarter flags (only for banks with landed multi-quarter history: WF 3511, Dime 6976)
- **F14 Peer Cluster** — the bank's behavioral group + sample peers
- **F13 Risk Score** — the deposit-flight model's score + diverging driver bars
- **F15 M&A Fit** — ranked partner candidates with rationale
- **F16 Stress Simulator** — live sliders (loan loss / deposit outflow / rate shock) driving a real capital waterfall and pass/fail verdict
- **Peer scatter** — the bank's position among all 1,000+ peers (CRE % vs uninsured %)

## Architecture

`services/api-gateway/src/bridge_server.py` is a dependency-free HTTP wrapper around
`banklens_mcp.tools` — the **same** functions the MCP server exposes to agents. The UI,
the MCP tools, and the CLIs all call identical feature logic; nothing is duplicated.

## Next (beyond this reference)
Land real Tiingo data (needs the user's key) to see the candlestick chart with
actual bars; move shared primitives into `frontend/packages/ui` and
`frontend/packages/charts` if a second app is added; swap the REST bridge for a
proper gRPC/REST gateway (Phase 5+ hardening).
