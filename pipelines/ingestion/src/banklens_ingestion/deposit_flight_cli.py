"""Feature 13 runner — train the deposit-flight model on a POOLED cross-section
spanning two real financial crises (2022Q4 -> 2023 failures, 2008Q1 -> IndyMac's
2008 failure), validate against real history, and save the model card.

    powershell -File scripts/deposit_flight.ps1
    python -m banklens_ingestion.deposit_flight_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.deposit_flight import (
    EXCLUDED_CANDIDATES, POSITIVE_CERTS, build_rows, leave_one_out, save_card,
    score_vector, train,
)


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _prior_deposits(data_dir: Path, repdte: str) -> dict[int, float]:
    recs = _load(data_dir / "bronze" / "source=fdic" / "deposits" / f"repdte={repdte}" / "records.json")
    return {int(r["CERT"]): float(r["DEP"]) * 1000 for r in recs if r.get("DEP") is not None}


def run(data_dir: Path) -> None:
    # 2022Q4 cross-section (pre-2023-failures), paired with 2021Q4 deposits for growth.
    recs22 = _load(data_dir / "bronze" / "source=fdic" / "population" / "repdte=20221231" / "records.json")
    rows_2022 = build_rows(recs22, _prior_deposits(data_dir, "20211231"))

    # 2008Q1 cross-section (pre-IndyMac-failure), paired with 2007Q1 deposits.
    recs08 = _load(data_dir / "bronze" / "source=fdic" / "population" / "repdte=20080331" / "records.json")
    rows_2008 = build_rows(recs08, _prior_deposits(data_dir, "20070331"))

    rows = rows_2022 + rows_2008
    card, fit = train(rows, trained_on="2022Q4 + 2008Q1")
    save_card(card)

    W = 84
    print("=" * W)
    print(f"  FEATURE 13 — DEPOSIT-FLIGHT EARLY-WARNING")
    print(f"  Pooled training: 2022Q4 (n={len(rows_2022)}) + 2008Q1 (n={len(rows_2008)}) = {len(rows)}")
    print("=" * W)
    print(f"  Positives (real failures, both crises): {', '.join(POSITIVE_CERTS.values())}")
    for cert, info in EXCLUDED_CANDIDATES.items():
        print(f"  Excluded: {info['name']} (CERT {cert}) — {info['reason']}")
    print(f"\n  In-sample ROC-AUC: {card['auc']}")
    print("\n  Coefficients (standardized; + raises modeled run-risk):")
    for f, w in sorted(zip(card["features"], card["weights"]), key=lambda t: abs(t[1]), reverse=True):
        print(f"    {f:<24} {w:+.3f}")

    # rank everyone; where do the actual failures land?
    scored = sorted(((r["cert"], r["name"], score_vector(card, r["features"])["risk_score"])
                     for r in rows), key=lambda t: t[2], reverse=True)
    print("\n  Riskiest banks by the model (top 8, both eras pooled):")
    for i, (c, n, s) in enumerate(scored[:8], 1):
        mark = "  <== ACTUAL FAILURE" if c in POSITIVE_CERTS else ""
        print(f"    {i:>2}. {s:.3f}  {(n or '')[:40]:<40}{mark}")

    print("\n  HONEST TEST — leave-one-out (retrain WITHOUT the bank, then score it "
          f"against the FULL pooled universe of all {len(rows)} banks, both eras):")
    for r in leave_one_out(rows):
        print(f"    {r['name']:<20} risk {r['risk']:.3f}  -> rank {r['rank']}/{r['n']} "
              f"({r['percentile']:.1f}th percentile)")

    # drivers for SVB and IndyMac — the two most contrasting cases
    for cert, label in ((24735, "SVB"), (29730, "IndyMac")):
        target = next((r for r in rows if r["cert"] == cert), None)
        if target:
            d = score_vector(card, target["features"])
            print(f"\n  Why {label} scores {d['risk_score']:.3f} — top drivers:")
            for drv in d["drivers"][:3]:
                print(f"    {drv['feature']:<24} = {drv['value']:>8}  (log-odds {drv['contribution']:+.2f})")
    print("=" * W)
    print(f"  Model card saved. In-sample AUC and leave-one-out are the honest checks.")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 13 — deposit-flight model")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
