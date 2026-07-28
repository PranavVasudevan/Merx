# Data contract — market EOD prices (`price_bars`)

Real end-of-day OHLCV candles, sourced from Tiingo, for the quant terminal's
candlestick charts. The one BankLens data source that genuinely requires the
user's own API key (a free tier, but not keyless like FDIC/SEC/Fed/FRED).

**Grain:** one row per (ticker, trading day). **License:** commercially licensed
(`config/sources.yaml`, `redistributable: false`) — display-only in this
architecture, never a bulk-export target.

## How a bank maps to a ticker

Market data is per-*ticker* (a public company), but BankLens features are per-
*bank* (an FDIC CERT). The bridge is the
[CERT↔CIK↔RSSD crosswalk](crosswalk.md) — `ticker_for_cert(cert)` in
`services/mcp-server/src/banklens_mcp/data.py` looks up a bank's ticker **only**
via `exact` or `high_confidence` crosswalk matches. A `low_confidence` match (like
Dime Community/Commercial's real naming discrepancy) is deliberately **not**
used here — showing the wrong company's stock chart under a bank's name would be
a much worse failure than just not having a chart yet.

## Columns

| Column | Type | Source (Tiingo field) | Notes |
|---|---|---|---|
| `ticker` | str | — | tagged during ingestion, not a Tiingo field |
| `date` | str | `date` | truncated from Tiingo's full timestamp to `YYYY-MM-DD` |
| `open` / `high` / `low` / `close` | num | `open`/`high`/`low`/`close` | as-traded |
| `volume` | num | `volume` | as-traded |
| `adj_close` / `adj_volume` | num | `adjClose`/`adjVolume` | split/dividend-adjusted |
| `div_cash` | num | `divCash` | cash dividend paid that day, if any |
| `split_factor` | num | `splitFactor` | 1.0 = no split that day |

## Gold derivations (`banklens_transforms.market`)

- `daily_returns` — simple day-over-day % change on `adj_close`
- `realized_volatility_annualized` — stdev of daily returns × √252, as a %, over a
  window (default 30 trading days)
- `fifty_two_week_range` — high/low over the trailing ~252 trading days
- `price_snapshot` — the single-row summary (latest close, 1-day change, 30-day
  vol, 52-week range) the KPI/snapshot view wants without the full candle series

## Landing

`scripts/land_market_data.ps1` reads `data/silver/crosswalk.json` (built by
`scripts/crosswalk.ps1`), takes only `exact`/`high_confidence` ticker matches,
and lands EOD history to `data/bronze/source=tiingo/daily/ticker=<TICKER>/records.json`.
Respects the free tier: a real per-call delay, a `--limit` batch size, and skips
tickers already landed within `--refresh-days` (default 1) so re-runs don't waste
quota. **Requires `TIINGO_API_KEY`** — this step was never run in the environment
this was built in (no key available); the connector, transforms, MCP tools, and
frontend chart are all built and tested up to that point.
