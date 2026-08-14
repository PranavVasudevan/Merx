"""Land the FDIC population (the full FDIC-insured universe, ~4,350 banks — widened
from the original $1B-$250B MVP slice, see docs/audit/04-remediation-prompts.md B3)
to Bronze, one or many quarters.

This is the connector that produced the landed population files — except that until
now it didn't exist. The Bronze partitions were created out-of-band, which is how
`population/repdte=20260331/_provenance.json` ended up hand-authored with no
`fetched_at`, no checksum, and an endpoint listing 34 fields where the records carry
44 (replaying that URL would not reproduce the file). Everything lands through
`Provenance.create()` here, so that class of drift can't recur.

One quarter is ONE request: the band holds ~1,050 banks against a 10,000-row ceiling.

    # a single quarter
    python -m banklens_ingestion.population_land_cli --repdte 20260331

    # a run of quarters (for QoQ/YoY and multi-bank filing diffs)
    python -m banklens_ingestion.population_land_cli --quarters 8

    powershell -File scripts/land_population.ps1
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.fdic import FdicSource

# FDIC reports quarterly on calendar quarter-ends.
_QUARTER_ENDS = ("0331", "0630", "0930", "1231")


def recent_quarters(latest: str, n: int) -> list[str]:
    """`n` REPDTEs ending at `latest` (YYYYMMDD), most recent first."""
    year, mmdd = int(latest[:4]), latest[4:]
    if mmdd not in _QUARTER_ENDS:
        raise ValueError(f"{latest} is not a quarter end (expected one of {_QUARTER_ENDS})")
    idx = _QUARTER_ENDS.index(mmdd)
    out = []
    for _ in range(n):
        out.append(f"{year}{_QUARTER_ENDS[idx]}")
        idx -= 1
        if idx < 0:
            idx = 3
            year -= 1
    return out


def land_quarter(src: FdicSource, repdte: str, data_dir: Path) -> int:
    rows, url = src.fetch_population(repdte)
    prov = Provenance.create(source=src.name, endpoint=url,
                             license=src.license, payload=rows)
    # B9 (docs/audit/04-remediation-prompts.md): a `landed=<date>` sub-partition,
    # not `population/repdte=X/records.json` directly — FDIC restates prior
    # quarters, and a flat path meant every re-land silently overwrote the
    # previous snapshot, so a number shown today could differ from the same
    # number shown last month with no way to reproduce which was "right" (both
    # were, as of when they were served). Bronze stays append-only in truth,
    # not just in the module docstring's claim: `data.population(as_of=...)`
    # picks the right snapshot from here. The landing date comes from the SAME
    # instant as `prov.fetched_at`, not a second clock reading.
    landed_date = datetime.fromisoformat(prov.fetched_at).strftime("%Y%m%d")
    write_partition(rows, prov, base_dir=data_dir / "bronze", source="fdic",
                    parts=("population", f"repdte={repdte}", f"landed={landed_date}"))
    print(f"  {repdte}: {len(rows):>5} banks   checksum {prov.checksum[:12]}...   "
          f"landed={landed_date}")
    return len(rows)


def run(repdtes: list[str], data_dir: Path) -> None:
    src = FdicSource()
    print(f"Landing the full FDIC population for {len(repdtes)} quarter(s)...")
    total = 0
    for q in repdtes:
        total += land_quarter(src, q, data_dir)
    print(f"Done. {total} bank-quarters across {len(repdtes)} partition(s).")


def main() -> None:
    p = argparse.ArgumentParser(description="Land the full FDIC population to Bronze")
    p.add_argument("--repdte", default="20260331", help="latest report date (YYYYMMDD)")
    p.add_argument("--quarters", type=int, default=1,
                   help="how many quarters back from --repdte to land (default 1)")
    p.add_argument("--data-dir", type=Path,
                   default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(recent_quarters(args.repdte, args.quarters), args.data_dir)


if __name__ == "__main__":
    main()
