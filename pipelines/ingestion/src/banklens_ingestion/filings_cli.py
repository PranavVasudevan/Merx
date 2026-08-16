"""Feature 17 (Tier 6 capstone) — land real SEC 10-K Item 1A risk-factor text
for banks the app already covers, extract it honestly (see
banklens_transforms.filing_extract for why that's the hard part), embed with
the already-pulled local nomic-embed-text ($0), and store in Postgres/pgvector.

Scope is deliberately bounded and disclosed, not silently partial: only banks
in the current landed population with a CONFIDENT (exact/high_confidence)
CERT<->CIK crosswalk match are eligible. Every skip (no confident match, no
10-K on file, low-confidence/failed extraction) is counted and printed, never
hidden.

B8 (docs/audit/04-remediation-prompts.md): this used to always land the same
`--limit` largest-by-assets banks every run — landing coverage could never
exceed whatever --limit the FIRST run happened to use, because every later
run re-attempted that same head and never reached anything past it. A
persisted CURSOR (data/bronze/source=sec/_filings_land_state.json) now
advances through the full eligible universe (stable order: sorted by CIK, not
re-sorted by a Gold column that can itself change between runs), round-robin
across runs, and a bank already landed within --refresh-days is skipped
without consuming this run's --limit — same pattern market_cli.py already
uses for Tiingo price landing.

    python -m banklens_ingestion.filings_cli --limit 40
    powershell -File scripts/land_filings.ps1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from banklens_common import embeddings
from banklens_common.db import delete_filing_chunks_for_cik, save_filing_chunks
from banklens_transforms.filing_extract import chunk_text, extract_item_1a
from banklens_transforms.silver import to_bank_financials

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.sec import SecSource

_STATE_FILENAME = "_filings_land_state.json"


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sec_root(data_dir: Path) -> Path:
    return data_dir / "bronze" / "source=sec"


def eligible_banks(data_dir: Path, repdte: str) -> list[dict]:
    """Every population bank with a confident crosswalk match — the same join
    `banklens_mcp.data.ticker_for_cert` does at serve time, done here once so
    the landing CLI doesn't need the whole MCP server import graph. Sorted by
    CIK (stable, never changes for a given filer) so the cursor's meaning
    doesn't shift if a re-crosswalk reorders rows or a bank's assets change
    its rank — B8's fix for the same "same head every run" bug this sort
    order itself used to cause when it was assets-descending."""
    pop_path = data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}" / "records.json"
    crosswalk_path = data_dir / "silver" / "crosswalk.json"
    pop_raw = _load(pop_path)
    crosswalk = _load(crosswalk_path)
    confident = {r["rssd"]: r for r in crosswalk if r["match_type"] in ("exact", "high_confidence")}

    out = []
    for r in pop_raw:
        s = to_bank_financials(r)
        rssd = s.get("holding_company_rssd") or s.get("rssd_id")
        match = confident.get(rssd)
        if match is None:
            continue
        out.append({
            "cert": s.get("cert_number"), "name": s.get("name"),
            "total_assets": s.get("total_assets"),
            "cik": match["cik"], "ticker": match["ticker"],
        })
    out.sort(key=lambda b: b["cik"])
    return out


def _load_state(data_dir: Path) -> dict:
    p = _sec_root(data_dir) / _STATE_FILENAME
    if not p.exists():
        return {"cursor": 0}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cursor": 0}
    return {"cursor": int(state.get("cursor", 0))}


def _save_state(data_dir: Path, cursor: int) -> None:
    p = _sec_root(data_dir) / _STATE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"cursor": cursor}, indent=2), encoding="utf-8")


def _already_fresh(data_dir: Path, cik: int, refresh_days: int) -> bool:
    """A bank is skipped (without consuming this run's --limit) if its filing
    partition is younger than --refresh-days — 10-Ks file annually, so
    re-fetching a bank landed last week wastes an SEC EDGAR call for no new
    data. `refresh_days` defaults long (see main()) precisely because of
    that cadence."""
    p = _sec_root(data_dir) / "filings" / f"cik={cik}" / "records.json"
    if not p.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    return age < timedelta(days=refresh_days)


def land_one(src: SecSource, bank: dict, data_dir: Path) -> dict:
    """Fetch, extract, chunk, embed and store one bank's latest 10-K. Returns a
    result dict for the run summary — never raises for an expected failure mode
    (no 10-K on file, extraction failed) so one bad filer doesn't kill the run."""
    cik = bank["cik"]
    try:
        latest = src.latest_10k(cik)
    except Exception as exc:
        return {**bank, "status": "fetch_error", "detail": str(exc)}
    if latest is None:
        return {**bank, "status": "no_10k_on_file", "detail": None}

    try:
        html = src.fetch_filing_document(cik, latest["accession"], latest["primary_document"])
    except Exception as exc:
        return {**bank, "status": "fetch_error", "detail": str(exc)}

    result = extract_item_1a(html)
    endpoint = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{latest['accession'].replace('-', '')}/{latest['primary_document']}")
    record = {
        "cik": cik, "cert": bank["cert"], "ticker": bank["ticker"], "name": bank["name"],
        "accession": latest["accession"], "filing_date": latest["filing_date"],
        "report_date": latest["report_date"], "extraction_confidence": result.confidence,
        "char_count": result.char_count, "extraction_reason": result.reason,
        "item_1a_text": result.text,
    }
    prov = Provenance.create(source=src.name, endpoint=endpoint, license=src.license,
                             payload=[record])
    write_partition([record], prov, base_dir=data_dir / "bronze", source="sec",
                    parts=("filings", f"cik={cik}"))

    if result.confidence != "high" or not result.text:
        return {**bank, "status": f"extraction_{result.confidence}", "detail": result.reason}

    chunks = chunk_text(result.text)
    chunk_rows = []
    for i, chunk in enumerate(chunks):
        vec = embeddings.embed(chunk)
        chunk_rows.append({
            "cik": cik, "cert": bank["cert"], "ticker": bank["ticker"], "name": bank["name"],
            "accession": latest["accession"], "filing_date": latest["filing_date"],
            "report_date": latest["report_date"], "extraction_confidence": result.confidence,
            "chunk_index": i, "chunk_text": chunk, "embedding": vec,
        })
    delete_filing_chunks_for_cik(cik)
    save_filing_chunks(chunk_rows)
    return {**bank, "status": "landed", "detail": f"{len(chunks)} chunks, {result.char_count} chars"}


def run(limit: int, refresh_days: int, repdte: str, data_dir: Path) -> None:
    banks = eligible_banks(data_dir, repdte)
    total_eligible = len(banks)
    if total_eligible == 0:
        print("No population banks have a confident CERT<->CIK crosswalk match yet "
              "(run scripts/crosswalk.ps1 first).")
        return

    state = _load_state(data_dir)
    cursor = state["cursor"] % total_eligible
    print(f"{total_eligible} population banks have a confident CERT<->CIK match; "
          f"resuming from cursor {cursor}, up to {limit} new lands this run "
          f"(skipping any already landed within {refresh_days} days).")

    src = SecSource()
    results: list[dict] = []
    skipped_fresh = 0
    idx = cursor
    for _ in range(total_eligible):   # at most one full lap of the eligible universe per run
        if len(results) >= limit:
            break
        bank = banks[idx]
        idx = (idx + 1) % total_eligible
        if _already_fresh(data_dir, bank["cik"], refresh_days):
            skipped_fresh += 1
            continue
        r = land_one(src, bank, data_dir)
        results.append(r)
        print(f"  [{len(results)}/{limit}] {bank['name'][:40]:<40} "
              f"({bank['ticker']})  {r['status']}"
              + (f" — {r['detail']}" if r.get("detail") else ""))
    _save_state(data_dir, idx)

    from collections import Counter
    counts = Counter(r["status"] for r in results)
    print("\n" + "=" * 70)
    print("  FEATURE 17 — SEC FILINGS LANDING SUMMARY")
    print("=" * 70)
    for status, n in counts.most_common():
        print(f"  {status:<24} {n}")
    print(f"  total attempted this run   {len(results)}")
    print(f"  skipped (already fresh)    {skipped_fresh}")
    print(f"  eligible universe          {total_eligible}")
    print(f"  cursor now at              {idx} (next run resumes here)")
    print("=" * 70)


def main() -> None:
    p = argparse.ArgumentParser(description="Land + embed SEC 10-K Item 1A risk factors")
    p.add_argument("--limit", type=int, default=40,
                   help="how many NEW banks to land this run (resumes from the "
                        "persisted cursor, not always the same head)")
    p.add_argument("--refresh-days", type=int, default=180,
                   help="skip a bank if already landed within this many days "
                        "(10-Ks file annually — no reason to re-fetch sooner)")
    p.add_argument("--repdte", default="20260331")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    try:
        run(args.limit, args.refresh_days, args.repdte, args.data_dir)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
