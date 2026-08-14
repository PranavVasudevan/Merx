"""Land FRED macro series to Bronze — Treasury yield curve, Fed funds,
unemployment, CRE price index (docs/audit/04-remediation-prompts.md B5).

Needs the user's own free `FRED_API_KEY` (get one, no card, at
https://fred.stlouisfed.org/docs/api/api_key.html) — the one series in
sources/fred.py's DEFAULT_SERIES that could NOT be live-verified in the
environment this was written in; see that module's docstring.

    python -m banklens_ingestion.fred_land_cli
    powershell -File scripts/land_fred.ps1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.fred import DEFAULT_SERIES, FredSource


def run(data_dir: Path, start_date: str | None) -> None:
    src = FredSource()
    print(f"Landing {len(DEFAULT_SERIES)} FRED series...")
    for label, series_id in DEFAULT_SERIES.items():
        rows, url = src.fetch_series(series_id, start_date=start_date)
        prov = Provenance.create(source=src.name, endpoint=url, license=src.license, payload=rows)
        write_partition(rows, prov, base_dir=data_dir / "bronze", source="fred",
                        parts=(f"series={series_id}",))
        latest = rows[-1] if rows else None
        print(f"  {label:<20} {series_id:<16} {len(rows):>5} observations   "
              f"latest {latest['date'] if latest else 'n/a'} = {latest['value'] if latest else 'n/a'}   "
              f"checksum {prov.checksum[:12]}...")


def main() -> None:
    p = argparse.ArgumentParser(description="Land FRED macro series to Bronze")
    p.add_argument("--start-date", default="2000-01-01",
                   help="earliest observation date (YYYY-MM-DD); FRED series often "
                        "start decades earlier, this keeps the landed set relevant")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir, args.start_date)


if __name__ == "__main__":
    main()
