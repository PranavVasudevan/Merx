"""Land the full annual FDIC Summary of Deposits (branch-level footprint) to Bronze.

Keyless, like the other FDIC sources — no API key needed, unlike Tiingo. One-time
(or annual-refresh) bulk pull: ~76k branch records across every FDIC-insured bank,
via ~8 paginated requests.

    powershell -File scripts/land_sod.ps1
    python -m banklens_ingestion.sod_cli --year 2025
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .sources.sod import SodSource


def run(year: int, data_dir: Path) -> None:
    print(f"Fetching FDIC Summary of Deposits for {year} (paginated, ~8 requests)...")
    src = SodSource()
    records = src.fetch_all_branches(year)
    print(f"  got {len(records)} branch records")

    out_dir = data_dir / "bronze" / "source=fdic" / "sod" / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Landed to {out_dir}\\records.json")


def main() -> None:
    p = argparse.ArgumentParser(description="Land the FDIC Summary of Deposits (branch footprint)")
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.year, args.data_dir)


if __name__ == "__main__":
    main()
