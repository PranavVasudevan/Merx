"""Land the full annual FDIC Summary of Deposits (branch-level footprint) to Bronze.

Keyless, like the other FDIC sources — no API key needed, unlike Tiingo. One-time
(or annual-refresh) bulk pull: ~76k branch records across every FDIC-insured bank,
via ~8 paginated requests.

    powershell -File scripts/land_sod.ps1
    python -m banklens_ingestion.sod_cli --year 2025
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.sod import SodSource


def run(year: int, data_dir: Path) -> None:
    print(f"Fetching FDIC Summary of Deposits for {year} (paginated, ~8 requests)...")
    src = SodSource()
    records = src.fetch_all_branches(year)
    print(f"  got {len(records)} branch records")
    placed = sum(1 for r in records if r.get("STCNTYBR") not in (None, ""))
    print(f"  {placed} carry a branch-level FIPS county ({placed / max(len(records), 1):.1%})")

    prov = Provenance.create(
        source=src.name, endpoint=src.page_url(year, 0),
        license=src.license, payload=records)
    path = write_partition(records, prov, base_dir=data_dir / "bronze",
                           source="fdic", parts=("sod", f"year={year}"))
    print(f"Landed to {path}  (checksum {prov.checksum[:12]}...)")


def main() -> None:
    p = argparse.ArgumentParser(description="Land the FDIC Summary of Deposits (branch footprint)")
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.year, args.data_dir)


if __name__ == "__main__":
    main()
