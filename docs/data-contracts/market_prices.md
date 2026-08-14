# Data contract — market prices (Tiingo EOD)

Source: `pipelines/ingestion/src/banklens_ingestion/sources/tiingo.py`,
Tiingo's End-of-Day API (`https://api.tiingo.com/tiingo/daily`). **Not**
public-domain — `license = "commercial-licensed"` (`config/sources.yaml`
tags it `redistributable: false`), unlike every other landed source in this
project. See "Licensing" below before treating this data the way FDIC/SEC/
EBA data is treated elsewhere.

## Auth and the one thing that can't be tested without a key

Free tier: 250 calls/day, up to 50 symbols/hour, ~5 years of EOD history, no
credit card — get a key at `https://api.tiingo.com/account/api/token` and set
`TIINGO_API_KEY` in `.env` (git-ignored). This is the **only** connector in
the project that genuinely can't be exercised without the user's own
credential (FDIC, SEC EDGAR and EBA are all keyless).

Auth is `Authorization: Token <key>` (a header, not a `?token=` query param)
specifically so the key never lands in a log line or in this connector's own
provenance `_source_url` field.

## Rate limiting

Two independent ceilings, enforced two different ways:

- **Per-call pacing** (`_MIN_DELAY_SECONDS = 2.0`, inside `TiingoSource._get`):
  paces requests *within* one run so a batch doesn't hammer Tiingo
  back-to-back. This does **not** by itself keep a run under the hourly
  symbol cap (2s × 50 symbols = 100s, nowhere near an hour).
- **The real hourly/daily ceilings** (`HOURLY_SYMBOL_CAP = 50`,
  `DAILY_CALL_CAP = 250`): enforced statefully, *across* runs, by
  `pipelines/ingestion/src/banklens_ingestion/market_cli.py`'s persisted
  call log (`_load_state`/`_calls_in_last_hour`) — this is what actually
  keeps the connector inside Tiingo's free-tier limits over a day of
  scheduled landing, not the per-call delay.

## Raw fields (`PRICE_FIELDS`, verified against Tiingo's own EOD docs page)

`date`, `open`, `high`, `low`, `close`, `volume`, `adjOpen`, `adjHigh`,
`adjLow`, `adjClose`, `adjVolume`, `divCash`, `splitFactor`. Every landed row
also carries `_ticker` and `_source_url`, attached by the connector (not
returned by Tiingo itself) so provenance survives past the raw fetch.

Rows arrive **oldest-to-newest last** per Tiingo's own ordering
(`fetch_daily_prices`'s docstring).

## Licensing (G3)

`config/sources.yaml` registers this source as `redistributable: false`.
Concretely: single-bank price display (the candlestick chart on a bank page)
is fine; bulk export of Tiingo-derived fields across many banks must be
gated or refused — see `docs/audit/04-remediation-prompts.md`'s G3 for the
enforcement requirement, and `banklens_mcp.tools.get_market_overview`'s
`performance_series_note` for where the aggregate cross-bank view already
omits per-bank price *series* once more than one bank is requested, while
still surfacing the aggregate analytics (beta, realized vol, drawdown) that
don't themselves redistribute the raw series.

## Downstream shape

Bronze rows land as-is (raw Tiingo field names, `_thousands`-free — Tiingo
reports actual price levels, not FDIC's thousands convention). The frontend
and MCP tools (`get_price_candles`, `get_market_snapshot`,
`get_market_overview`) consume a normalised `PriceBar` shape
(`frontend/apps/web/src/types.ts`): `ticker`, `date`, `open`, `high`, `low`,
`close`, `volume`, `adj_close` — the `adj*`-prefixed Tiingo fields collapse
to their canonical snake_case names, and split/dividend-adjustment fields
not needed downstream (`divCash`, `splitFactor`, the non-close `adj*`
variants) are dropped rather than carried through every layer unused.
