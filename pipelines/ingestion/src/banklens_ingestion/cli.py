"""Phase-1 vertical slice: one bank, end to end.

    fetch (FDIC)  ->  land Bronze  ->  normalise Silver  ->  derive Gold  ->  show

Run it (from the repo root, no installs needed)::

    powershell -File scripts/run_vertical_slice.ps1            # Wells Fargo (CERT 3511)
    powershell -File scripts/run_vertical_slice.ps1 -Cert 628  # JPMorgan Chase

Or directly::

    $env:PYTHONPATH = "pipelines/ingestion/src;pipelines/transforms/src"
    python -m banklens_ingestion.cli --cert 3511 --quarters 6

This is deliberately chatty — it explains each banking metric as it prints, so
the pipeline doubles as a lesson in reading a bank's balance sheet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.gold import derive_gold
from banklens_transforms.silver import to_bank_financials

from .bronze.writer import write_bronze
from .provenance import Provenance
from .sources.fdic import FdicSource


def _fmt_usd(value) -> str:
    if value is None:
        return "n/a"
    return f"${value/1e9:,.2f}B"


def _fmt_pct(value) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def run(cert: int, quarters: int, data_dir: Path) -> None:
    src = FdicSource()

    print(f"\n[1/4] FETCH  — FDIC BankFind, CERT {cert}")
    profile = src.get_institution(cert)
    print(f"        {profile.get('NAME')}  ({profile.get('CITY')}, {profile.get('STALP')})")
    raw = src.fetch(cert, quarters=quarters)
    print(f"        pulled {len(raw)} quarterly records")

    print("[2/4] BRONZE — landing raw bytes + provenance (immutable)")
    prov = Provenance.create(
        source=src.name, endpoint=raw[0].get("_source_url", ""),
        license=src.license, payload=raw,
    )
    bronze_dir = data_dir / "bronze"
    landed = write_bronze(raw, prov, base_dir=bronze_dir, source="fdic", cert=cert)
    print(f"        -> {landed}")
    print(f"        checksum {prov.checksum[:16]}...  fetched_at {prov.fetched_at}")

    print("[3/4] SILVER — normalise (thousands->USD, parse dates, map codes)")
    silver = [to_bank_financials(r) for r in raw]
    (data_dir / "silver").mkdir(parents=True, exist_ok=True)
    (data_dir / "silver" / f"cert={cert}.json").write_text(
        json.dumps(silver, indent=2), encoding="utf-8")

    print("[4/4] GOLD   — derive features (build once, reuse everywhere)\n")
    gold = derive_gold(silver)
    (data_dir / "gold").mkdir(parents=True, exist_ok=True)
    (data_dir / "gold" / f"cert={cert}.json").write_text(
        json.dumps(gold, indent=2), encoding="utf-8")

    # ---- human-readable report -------------------------------------------
    latest_s, latest_g = silver[0], gold[0]
    print("=" * 66)
    print(f"  {latest_s['name']}  —  {latest_s['quarter']}  ({latest_s['filing_date']})")
    print("=" * 66)
    print(f"  Total assets .............. {_fmt_usd(latest_s['total_assets'])}")
    print(f"  Total deposits ............ {_fmt_usd(latest_s['total_deposits'])}")
    print(f"    of which insured ........ {_fmt_usd(latest_s['insured_deposits'])}")
    print(f"    of which UNINSURED ...... {_fmt_usd(latest_s['uninsured_deposits'])}")
    print(f"  Net loans & leases ........ {_fmt_usd(latest_s['total_loans_net'])}")
    print(f"  Total equity capital ...... {_fmt_usd(latest_s['total_equity'])}")
    print("  " + "-" * 62)
    print("  GOLD FEATURES")
    print(f"  Uninsured deposit %  ...... {_fmt_pct(latest_g['uninsured_deposit_pct'])}"
          "   <- #1 deposit-flight signal")
    print(f"  Loan-to-deposit %  ........ {_fmt_pct(latest_g['loan_to_deposit_pct'])}"
          "   <- funding intensity")
    print(f"  Equity-to-assets %  ....... {_fmt_pct(latest_g['equity_to_assets_pct'])}"
          "   <- leverage proxy")
    if latest_g["qoq_total_deposits"]:
        d = latest_g["qoq_total_deposits"]
        print(f"  Deposits QoQ  ............. {_fmt_usd(d['abs'])} ({d['pct']:+.2f}%)"
              "   <- outflow/inflow this quarter")
    print("=" * 66)
    print("  Trend (newest -> oldest):")
    for g in gold:
        print(f"    {g['quarter']:>7}   uninsured {_fmt_pct(g['uninsured_deposit_pct']):>7}"
              f"   L/D {_fmt_pct(g['loan_to_deposit_pct']):>7}")
    print(f"\n  Wrote Silver + Gold JSON under {data_dir}\\  — open them to inspect.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="BankLens Phase-1 vertical slice")
    parser.add_argument("--cert", type=int, default=3511,
                        help="FDIC certificate number (default 3511 = Wells Fargo Bank NA)")
    parser.add_argument("--quarters", type=int, default=6,
                        help="how many recent quarters to pull")
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parents[4] / "data",
                        help="where to land bronze/silver/gold (default: repo data/)")
    args = parser.parse_args()
    run(args.cert, args.quarters, args.data_dir)


if __name__ == "__main__":
    main()
