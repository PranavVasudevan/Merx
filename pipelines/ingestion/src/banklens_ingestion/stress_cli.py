"""Feature 16 runner — stress-test one bank's real balance sheet.

Run (after landing the bank's Bronze data with capital-dollar fields)::

    powershell -File scripts/stress_test.ps1 -Cert 3511 -LoanLoss 4 -Outflow 25 -RateBps 250
    # or:
    $env:PYTHONPATH = "pipelines/ingestion/src;pipelines/transforms/src"
    python -m banklens_ingestion.stress_cli --cert 3511 --loan-loss 4 --outflow 25 --rate-bps 250
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.silver import to_bank_financials
from banklens_transforms.stress import (
    Shock, run_stress_test, run_stress_test_quantlib, starting_position,
)

_LABELS = {"cet1": "CET1", "tier1": "Tier 1 RBC", "total": "Total RBC", "leverage": "Tier 1 leverage"}


def _b(v) -> str:
    return "n/a" if v is None else f"${v/1e9:,.2f}B"


def run(cert: int, data_dir: Path, loan_loss: float, outflow: float, rate_bps: float,
       compare_quantlib: bool = False) -> None:
    bronze = data_dir / "bronze" / "source=fdic" / f"cert={cert}" / "records.json"
    raw = json.loads(bronze.read_text(encoding="utf-8-sig"))
    silver = to_bank_financials(raw[0])          # latest quarter (records are DESC)
    pos = starting_position(silver)

    if pos["tier1_capital"] is None or pos["rwa"] is None:
        print(f"  Missing capital-dollar fields for CERT {cert}. Re-land Bronze with the "
              f"extended field set (RBCT1J, RBC, RWAJT).")
        return

    shock = Shock(loan_loss_pct=loan_loss, deposit_outflow_pct=outflow, rate_shock_bps=rate_bps)
    res = run_stress_test(pos, shock)

    W = 72
    print("=" * W)
    print("  FEATURE 16 — CAPITAL BUFFER SIMULATOR")
    print(f"  {pos['name']}  —  {pos['quarter']}")
    print("=" * W)
    print(f"  Starting balance sheet:  Tier1 {_b(pos['tier1_capital'])}   RWA {_b(pos['rwa'])}")
    print(f"    loans {_b(pos['total_loans'])}   deposits {_b(pos['total_deposits'])}   "
          f"cash {_b(pos['cash'])}")
    print(f"    securities AFS {_b(pos['securities_afs'])} / HTM {_b(pos['securities_htm'])}")
    print("\n  SCENARIO")
    print(f"    loan losses {loan_loss:.1f}%   deposit outflow {outflow:.1f}%   "
          f"rate shock +{rate_bps:.0f} bps")

    print("\n  CAPITAL WATERFALL (what erodes capital)")
    w = res["capital_waterfall"]
    print(f"    loan losses ......... {_b(w['loan_loss'])}")
    print(f"    AFS mark-to-market .. {_b(w['afs_mark_loss'])}")
    print(f"    realized HTM loss ... {_b(w['htm_realized_loss'])}")
    print(f"    -> total capital hit  {_b(w['total_capital_hit'])}")

    liq = res["liquidity"]
    print("\n  LIQUIDITY / SVB CHAIN")
    print(f"    deposit outflow {_b(liq['deposit_outflow'])}  vs  liquidity {_b(liq['available_liquidity'])}")
    if liq["shortfall_forcing_htm_sales"] > 0:
        print(f"    shortfall {_b(liq['shortfall_forcing_htm_sales'])} FORCES selling "
              f"{liq['htm_sold_fraction']*100:.0f}% of HTM -> loss becomes REAL")
    else:
        print(f"    liquidity covers the outflow — HTM losses stay unrealized "
              f"(memo: {_b(liq['htm_unrealized_loss_memo'])} hidden)")

    print("\n  CAPITAL RATIOS         before   ->   after     min    verdict")
    for k in ("cet1", "tier1", "total", "leverage"):
        mark = "PASS" if res["passes"][k] else "** FAIL **"
        print(f"    {_LABELS[k]:<18} {res['before'][k]:>6.2f}%  -> {res['after'][k]:>6.2f}%   "
              f"{res['minimums'][k]:>5.1f}%   {mark}")
    print("\n  OVERALL: " + ("PASS — stays above all regulatory minimums"
                             if res["passes_all"] else "FAIL — breaches a regulatory minimum"))
    print("=" * W)

    if compare_quantlib:
        ql_res = run_stress_test_quantlib(pos, shock)
        ql_w = ql_res["capital_waterfall"]
        print("\n  COMPARISON — linear duration approx (above) vs real QuantLib DCF re-price")
        print(f"    AFS mark-to-market:  linear {_b(w['afs_mark_loss'])}   vs   "
              f"quantlib {_b(ql_w['afs_mark_loss'])}")
        print(f"    total capital hit:   linear {_b(w['total_capital_hit'])}   vs   "
              f"quantlib {_b(ql_w['total_capital_hit'])}")
        print(f"    CET1 after shock:    linear {res['after']['cet1']:.2f}%   vs   "
              f"quantlib {ql_res['after']['cet1']:.2f}%")
        print("    (convexity means the real re-price is always a SMALLER loss than the "
              "linear approximation for a given yield rise — see quantlib_pricing.py)")
        print("=" * W)


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 16 — capital buffer stress test")
    p.add_argument("--cert", type=int, default=3511)
    p.add_argument("--loan-loss", type=float, default=3.0, help="%% of loans lost")
    p.add_argument("--outflow", type=float, default=15.0, help="%% of deposits withdrawn")
    p.add_argument("--rate-bps", type=float, default=200.0, help="parallel rate rise (bps)")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    p.add_argument("--quantlib", action="store_true",
                   help="also show the real QuantLib DCF re-price alongside the linear approximation")
    args = p.parse_args()
    run(args.cert, args.data_dir, args.loan_loss, args.outflow, args.rate_bps,
        compare_quantlib=args.quantlib)


if __name__ == "__main__":
    main()
