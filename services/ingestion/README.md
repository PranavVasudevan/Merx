# services/ingestion — production connector SDK (Rust)

**Status: real, not a skeleton.** Ports the FDIC BankFind connector from
`pipelines/ingestion/src/banklens_ingestion/sources/fdic.py` to Rust
(`tokio` + `reqwest`), landing to the exact same Bronze partition layout
(`data/bronze/source=fdic/cert=<N>/records.json` + `_provenance.json`) so
either engine's output is a drop-in for the other — verified by landing a
real cert with this Rust binary and running the untouched Python Silver/Gold/
X-Ray pipeline against it.

## Scope — read this before assuming more is ported than is

Only the FDIC `financials` fetch is ported. **Not** ported: SEC EDGAR, Tiingo,
FDIC SOD (branch footprints), or the CIK/RSSD crosswalk — those remain
Python-only (`pipelines/ingestion`), which stays authoritative for them.
`Silver`/`Gold`/`X-Ray` transforms also stay Python (`pipelines/transforms`) —
this crate is Bronze-layer only, matching its original design intent.

## The actual throughput story

The Python connector fetches one cert per synchronous process. This crate's
`fetch-many` subcommand fetches N certs **concurrently** (bounded by
`--concurrency`, default 4, to stay polite to the FDIC API) — see
`CHANGELOG.md` for a real measured benchmark, not a claimed one.

## The real scraper: FDIC failed-bank narrative detail

`src/sources/fdic_failures.rs` scrapes FDIC's "Failed Bank Information" pages
(`fdic.gov/resources/resolutions/bank-failures/failed-bank-list/<slug>.html`)
— real HTML scraping, because **no API exists for this content**. FDIC's own
BankFind `/api/failures` endpoint gives structured facts (CERT, closing date,
resolution type) — that's the bulk/API half, already covered by existing
sources. This scraper is only for what that endpoint doesn't have: the
resolution narrative (receiver, acquiring institution, deposit-transfer
terms, holding-company involvement) and links to the official press
release(s) — exactly the master plan's own example of a legitimate scrape
target ("press-release failure detail").

Politeness, verified against the real `robots.txt` before writing any of
this: discovery is sitemap-only (`fdic.gov/sitemap.xml`, which `robots.txt`
itself points to) — URL slugs are never guessed — and every request is
spaced at least 1 second apart (`robots.txt`: `Crawl-delay: 1`).

```powershell
# targeted: the failures this project's deposit-flight model was already validated against
cargo run --release --bin banklens-ingest -- scrape-failures --slugs signature-ny,silicon-valley,first-republic,indymac,heartlandtristate

# or discover the full list via the sitemap (569 pages as of this writing) and take the first N
cargo run --release --bin banklens-ingest -- scrape-failures --discover-limit 10
```

Lands to `data/bronze/source=fdic_failure_narrative/slug=<slug>/records.json`
— keyed by URL slug, not CERT, since Bronze stays raw; joining a slug to a
CERT is a Silver-layer step (against BankFind's `/api/failures`) that hasn't
been built yet.

## Install

```powershell
winget install --id Rustlang.Rustup -e
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--add Microsoft.VisualStudio.Workload.VCTools"
```

(the MSVC C++ workload is required for Rust's default Windows toolchain to
link — it's also what the planned QuantLib/C++ integration needs, so
installing it once covers both workstreams.)

## Run

```powershell
cargo run --release --bin banklens-ingest -- fetch --cert 3511 --quarters 8
cargo run --release --bin banklens-ingest -- fetch-many --certs 3511,6976,16068 --quarters 8 --concurrency 4
cargo run --release --bin banklens-ingest -- scrape-failures --slugs signature-ny,silicon-valley
cargo test
```
