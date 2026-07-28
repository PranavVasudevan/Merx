# pipelines/ingestion — Bronze connectors (Python reference)

Each source implements the `Source` contract (`sources/base.py`): fetch raw
records, attach provenance, land immutably in Bronze.

## Implemented
- **FDIC BankFind** (`sources/fdic.py`) — institution profile + quarterly financials. Public REST, no auth. Verified field codes: `ASSET, DEP, DEPINS, LNLSGR, LNLSNET, EQ, REPDTE`, plus loan composition, capital dollars/ratios, and holding-company identity (`NAMEHCR`/`RSSDHCR`/`RSSDID`).
- **SEC EDGAR** (`sources/sec.py`) — the ticker/CIK directory (`company_tickers.json`) and per-filer XBRL company facts (`companyfacts/CIK##########.json`). Public REST, identifying User-Agent + 10 req/s cap enforced. Feeds the [CERT↔CIK↔RSSD crosswalk](../../docs/data-contracts/crosswalk.md) (`banklens_transforms.crosswalk`, run via `scripts/crosswalk.ps1`).

- **Tiingo** (`sources/tiingo.py`) — real EOD OHLCV prices. Public REST, but genuinely requires a free API key (unlike FDIC/SEC) — `TIINGO_API_KEY`. Feeds `get_price_candles`/`get_market_snapshot` via the crosswalk. Land it with `scripts/land_market_data.ps1`.

## Planned (Phase 2)
- FFIEC CDR (Call Reports / UBPR via the Public Web Service)
- Fed NIC (FR Y-9C holding-company data)
- FRED (macro series)

## Run
```powershell
$env:PYTHONPATH = "src;../transforms/src"
python -m banklens_ingestion.cli --cert 3511 --quarters 6   # fetch + transform
python -m banklens_ingestion.cli --cert 3511 --from-bronze  # re-run transforms, no network
```

`--from-bronze` replays the Silver→Gold→X-Ray transforms on already-landed Bronze —
useful for offline iteration and if the source is temporarily throttling you.

## Politeness / throttling
The connector sends an identifying User-Agent, a per-request delay, and bounded
retries with backoff, and issues a **single** financials request per bank. Heavy
bursts (e.g. rapid field-probing) can trip FDIC's CDN into rate-limiting your IP
(seen as TLS connection resets). Keep request volume modest; the production Rust
connector will add connection reuse and adaptive backoff.

## Test (hermetic, no network)
```powershell
python tests/test_fdic.py
```

The production connector SDK migrates to Rust under `services/ingestion` once the
data shapes are well understood — same contract, higher throughput and safety.
