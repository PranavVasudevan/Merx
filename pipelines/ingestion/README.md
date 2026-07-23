# pipelines/ingestion — Bronze connectors (Python reference)

Each source implements the `Source` contract (`sources/base.py`): fetch raw
records, attach provenance, land immutably in Bronze.

## Implemented
- **FDIC BankFind** (`sources/fdic.py`) — institution profile + quarterly financials. Public REST, no auth. Verified field codes: `ASSET, DEP, DEPINS, LNLSGR, LNLSNET, EQ, REPDTE`.

## Planned (Phase 1–2)
- FFIEC CDR (Call Reports / UBPR via the Public Web Service)
- SEC EDGAR (CompanyFacts / Frames; needs an identifying User-Agent, 10 req/s cap)
- Fed NIC (FR Y-9C holding-company data)
- FRED (macro series), market OHLC (Phase 2)

## Run
```powershell
$env:PYTHONPATH = "src;../transforms/src"
python -m banklens_ingestion.cli --cert 3511 --quarters 6
```

## Test (hermetic, no network)
```powershell
python tests/test_fdic.py
```

The production connector SDK migrates to Rust under `services/ingestion` once the
data shapes are well understood — same contract, higher throughput and safety.
