"""Feature 12 runner — diff a bank's filings between two quarters.

    powershell -File scripts/filing_diff.ps1 -Cert 6976
    python -m banklens_ingestion.filing_diff_cli --cert 6976 --quarter-a 2024Q4 --quarter-b 2026Q1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.silver import to_bank_financials

_ARROW = {"up": "▲", "down": "▼"}


def run(cert: int, data_dir: Path, quarter_a: str | None, quarter_b: str | None,
        z_threshold: float) -> None:
    bronze = data_dir / "bronze" / "source=fdic" / f"cert={cert}" / "records.json"
    raw = json.loads(bronze.read_text(encoding="utf-8-sig"))
    quarters = build_quarters([to_bank_financials(r) for r in raw])
    res = diff(quarters, quarter_a, quarter_b, z_threshold=z_threshold)

    W = 74
    print("=" * W)
    print(f"  FEATURE 12 — FILING DIFF")
    print(f"  {res['name']}   {res['from_quarter']} -> {res['to_quarter']} "
          f"({res['span_quarters']}Q)")
    print("=" * W)
    print(f"  Flags: material moves that are outliers vs this bank's own history "
          f"(|z| >= {z_threshold})\n")
    if not res["flags"]:
        print("    No unusual line-item shifts — filings are steady vs the bank's norm.")
    for f in res["flags"]:
        z = f"z={f['z']:+.1f}" if f["z"] is not None else "z=n/a"
        sign = "+" if f["change"] > 0 else ""
        print(f"    {_ARROW[f['direction']]} {f['item']:<22} {sign}{f['change']}{f['unit']:<2}  "
              f"({z})")
        print(f"        {f['note']}")
    print("=" * W)
    out = data_dir / "gold" / f"cert={cert}.filingdiff.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 12 — filing diff")
    p.add_argument("--cert", type=int, default=6976)
    p.add_argument("--quarter-a", default=None, help="older quarter (default: 2nd-newest)")
    p.add_argument("--quarter-b", default=None, help="newer quarter (default: newest)")
    p.add_argument("--z-threshold", type=float, default=2.0)
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.cert, args.data_dir, args.quarter_a, args.quarter_b, args.z_threshold)


if __name__ == "__main__":
    main()
