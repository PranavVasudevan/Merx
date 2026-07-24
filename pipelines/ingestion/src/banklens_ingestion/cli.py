"""Phase-1 vertical slice: one bank, end to end.

    fetch (FDIC)  ->  land Bronze  ->  normalise Silver  ->  derive Gold  ->  X-Ray

Run it (from the repo root, no installs needed)::

    powershell -File scripts/run_vertical_slice.ps1            # Wells Fargo (CERT 3511)
    powershell -File scripts/run_vertical_slice.ps1 -Cert 628  # JPMorgan Chase

Or directly::

    $env:PYTHONPATH = "pipelines/ingestion/src;pipelines/transforms/src"
    python -m banklens_ingestion.cli --cert 3511 --quarters 6

Deliberately chatty — it explains each banking metric as it prints, so the
pipeline doubles as a lesson in reading a bank's balance sheet.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.gold import LOAN_CATEGORIES, derive_gold
from banklens_transforms.silver import to_bank_financials
from banklens_transforms.xray import evaluate_xray

from .bronze.writer import write_bronze
from .provenance import Provenance
from .sources.fdic import FdicSource

_SEV_MARK = {"high": "[HIGH]", "elevated": "[ELEV]", "low": "[ ok ]"}


def _usd(value) -> str:
    return "n/a" if value is None else f"${value/1e9:,.2f}B"


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def run(cert: int, quarters: int, data_dir: Path, from_bronze: bool = False) -> None:
    src = FdicSource()
    bronze_records = data_dir / "bronze" / "source=fdic" / f"cert={cert}" / "records.json"

    if from_bronze:
        print(f"\n[1/4] LOAD   — reading already-landed Bronze for CERT {cert}")
        raw = json.loads(bronze_records.read_text(encoding="utf-8-sig"))  # tolerate BOM
        print(f"        {len(raw)} records from {bronze_records}")
    else:
        print(f"\n[1/4] FETCH  — FDIC BankFind, CERT {cert} (single request)")
        raw = src.fetch(cert, quarters=quarters)   # financials carry NAMEFULL/STALP already
        print(f"        pulled {len(raw)} quarterly records, {len(raw[0])} fields each")
        print("[2/4] BRONZE — landing raw bytes + provenance (immutable)")
        prov = Provenance.create(src.name, raw[0].get("_source_url", ""), src.license, raw)
        landed = write_bronze(raw, prov, base_dir=data_dir / "bronze", source="fdic", cert=cert)
        print(f"        -> {landed}  (checksum {prov.checksum[:12]}...)")

    print("[3/4] SILVER — normalise (thousands->USD, ratios pass-through, CRE aggregate)")
    silver = [to_bank_financials(r) for r in raw]
    (data_dir / "silver").mkdir(parents=True, exist_ok=True)
    (data_dir / "silver" / f"cert={cert}.json").write_text(
        json.dumps(silver, indent=2), encoding="utf-8")

    print("[4/4] GOLD   — concentration, capital, funding features\n")
    gold = derive_gold(silver)
    (data_dir / "gold").mkdir(parents=True, exist_ok=True)
    (data_dir / "gold" / f"cert={cert}.json").write_text(
        json.dumps(gold, indent=2), encoding="utf-8")

    s, g = silver[0], gold[0]
    W = 68
    print("=" * W)
    print(f"  {s['name']}  —  {s['quarter']}  ({s['filing_date']})")
    print("=" * W)
    print("  BALANCE SHEET")
    print(f"    Total assets ............ {_usd(s['total_assets'])}")
    print(f"    Total deposits .......... {_usd(s['total_deposits'])}")
    print(f"      insured / UNINSURED ... {_usd(s['insured_deposits'])} / {_usd(s['uninsured_deposits'])}")
    print(f"    Net loans & leases ...... {_usd(s['total_loans_net'])}")
    print(f"    Securities AFS / HTM .... {_usd(s['securities_afs'])} / {_usd(s['securities_htm'])}")
    print(f"    Total equity ............ {_usd(s['total_equity'])}")

    print("\n  LOAN COMPOSITION (% of gross loans)")
    for col, label in LOAN_CATEGORIES.items():
        amt = s.get(col)
        conc = g.get(f"concentration_ratio_{label}")
        bar = "#" * int((conc or 0) / 2.5)
        print(f"    {label:<22} {_usd(amt):>10}  {_pct(conc):>7}  {bar}")

    print("\n  CAPITAL ADEQUACY (regulatory ratios, from FDIC)")
    print(f"    CET1 ................ {_pct(g['cet1_ratio'])}   (Basel min+buffer ~10.5%)")
    print(f"    Tier 1 RBC ......... {_pct(g['tier1_rbc_ratio'])}")
    print(f"    Total RBC .......... {_pct(g['total_rbc_ratio'])}")
    print(f"    Tier 1 leverage .... {_pct(g['leverage_ratio'])}   (well-capitalized >=5%)")

    # ---- Feature 11: X-Ray -------------------------------------------------
    xray = evaluate_xray(g)
    (data_dir / "gold" / f"cert={cert}.xray.json").write_text(
        json.dumps(xray, indent=2), encoding="utf-8")
    print("\n  " + "-" * (W - 4))
    print(f"  FEATURE 11 — BALANCE-SHEET X-RAY    overall risk: {xray['overall_risk'].upper()}"
          f"  ({xray['flag_count']} flag(s))")
    if not xray["flags"]:
        print("    No structural outliers vs thresholds — diversified, well-capitalized.")
    for f in xray["flags"]:
        print(f"    {_SEV_MARK[f['severity']]} {f['factor']}: {f['value']} "
              f"(threshold {f['threshold']})")
        print(f"           {f['note']}")

    print("\n  TREND (uninsured % · loan/deposit · CET1)")
    for gg in gold:
        print(f"    {gg['quarter']:>7}   uninsured {_pct(gg['uninsured_deposit_pct']):>7}"
              f"   L/D {_pct(gg['loan_to_deposit_pct']):>7}   CET1 {_pct(gg['cet1_ratio']):>7}")
    print("=" * W)
    print(f"  Wrote Silver + Gold + X-Ray JSON under {data_dir}\\\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="BankLens Phase-1 vertical slice")
    parser.add_argument("--cert", type=int, default=3511,
                        help="FDIC certificate number (default 3511 = Wells Fargo Bank NA)")
    parser.add_argument("--quarters", type=int, default=6, help="recent quarters to pull")
    parser.add_argument("--from-bronze", action="store_true",
                        help="skip the network; re-run transforms on already-landed Bronze")
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parents[4] / "data",
                        help="where to land bronze/silver/gold (default: repo data/)")
    args = parser.parse_args()
    run(args.cert, args.quarters, args.data_dir, from_bronze=args.from_bronze)


if __name__ == "__main__":
    main()
