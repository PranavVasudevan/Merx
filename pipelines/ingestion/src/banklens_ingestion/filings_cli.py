"""Feature 17 (Tier 6 capstone), Wave A+B+C — land real SEC 10-K Item 1A risk-factor
text for banks the app already covers, extract it honestly (see
banklens_transforms.filing_extract for why that's the hard part), embed with the
already-pulled local nomic-embed-text ($0), and store in Postgres/pgvector.

Scope is deliberately bounded and disclosed, not silently partial: only banks in
the CURRENT $1B-$250B population with a CONFIDENT (exact/high_confidence)
CERT<->CIK crosswalk match are eligible — verified live, 283 of ~1,049 population
banks qualify. --limit caps how many of those (by assets, largest first) get
landed in one run; re-run with a higher --limit to extend coverage. Every skip
(no confident match, no 10-K on file, low-confidence/failed extraction) is
counted and printed, never hidden.

    python -m banklens_ingestion.filings_cli --limit 40
    powershell -File scripts/land_filings.ps1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from banklens_common import embeddings
from banklens_common.db import delete_filing_chunks_for_cik, save_filing_chunks
from banklens_transforms.filing_extract import chunk_text, extract_item_1a
from banklens_transforms.silver import to_bank_financials

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.sec import SecSource


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def eligible_banks(data_dir: Path, repdte: str) -> list[dict]:
    """Population banks with a confident crosswalk match, largest by assets first —
    the same join `banklens_mcp.data.ticker_for_cert` does at serve time, done
    here once so the landing CLI doesn't need the whole MCP server import graph."""
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
    out.sort(key=lambda b: b["total_assets"] or 0, reverse=True)
    return out


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


def run(limit: int, repdte: str, data_dir: Path) -> None:
    banks = eligible_banks(data_dir, repdte)
    print(f"{len(banks)} population banks have a confident CERT<->CIK match "
          f"(landing the {min(limit, len(banks))} largest by assets)...")
    src = SecSource()
    results = []
    for i, bank in enumerate(banks[:limit], 1):
        r = land_one(src, bank, data_dir)
        results.append(r)
        print(f"  [{i}/{min(limit, len(banks))}] {bank['name'][:40]:<40} "
              f"({bank['ticker']})  {r['status']}"
              + (f" — {r['detail']}" if r.get("detail") else ""))

    from collections import Counter
    counts = Counter(r["status"] for r in results)
    print("\n" + "=" * 70)
    print("  FEATURE 17 — SEC FILINGS LANDING SUMMARY")
    print("=" * 70)
    for status, n in counts.most_common():
        print(f"  {status:<24} {n}")
    print(f"  total attempted          {len(results)}")
    print(f"  population banks NOT yet attempted (raise --limit to cover more): "
          f"{max(0, len(banks) - limit)}")
    print("=" * 70)


def main() -> None:
    p = argparse.ArgumentParser(description="Land + embed SEC 10-K Item 1A risk factors")
    p.add_argument("--limit", type=int, default=40,
                   help="how many eligible banks (largest by assets) to land this run")
    p.add_argument("--repdte", default="20260331")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    try:
        run(args.limit, args.repdte, args.data_dir)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
