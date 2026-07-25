"""Feature 13 runner — train the deposit-flight model on 2022Q4, validate against
the real 2023 failures, and save the model card.

    powershell -File scripts/deposit_flight.ps1
    python -m banklens_ingestion.deposit_flight_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.deposit_flight import (
    POSITIVE_CERTS, build_rows, leave_one_out, save_card, score_vector, train,
)


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(data_dir: Path) -> None:
    recs22 = _load(data_dir / "bronze" / "source=fdic" / "population" / "repdte=20221231" / "records.json")
    recs21 = _load(data_dir / "bronze" / "source=fdic" / "deposits" / "repdte=20211231" / "records.json")
    prior = {int(r["CERT"]): float(r["DEP"]) * 1000 for r in recs21 if r.get("DEP") is not None}

    rows = build_rows(recs22, prior)
    card, fit = train(rows)
    save_card(card)

    W = 80
    print("=" * W)
    print(f"  FEATURE 13 — DEPOSIT-FLIGHT EARLY-WARNING   (trained on 2022Q4, n={len(rows)})")
    print("=" * W)
    print(f"  Positives (known 2023 failures): {', '.join(POSITIVE_CERTS.values())}")
    print(f"  In-sample ROC-AUC: {card['auc']}")
    print("\n  Coefficients (standardized; + raises modeled run-risk):")
    for f, w in sorted(zip(card["features"], card["weights"]), key=lambda t: abs(t[1]), reverse=True):
        print(f"    {f:<24} {w:+.3f}")

    # rank everyone; where do the actual failures land?
    scored = sorted(((r["cert"], r["name"], score_vector(card, r["features"])["risk_score"])
                     for r in rows), key=lambda t: t[2], reverse=True)
    print("\n  Riskiest banks by the model (top 8):")
    for i, (c, n, s) in enumerate(scored[:8], 1):
        mark = "  <== ACTUAL FAILURE" if c in POSITIVE_CERTS else ""
        print(f"    {i:>2}. {s:.3f}  {(n or '')[:40]:<40}{mark}")

    print("\n  HONEST TEST — leave-one-out (retrain WITHOUT the bank, then score it):")
    for r in leave_one_out(rows):
        print(f"    {r['name']:<24} risk {r['risk']:.3f}  -> rank {r['rank']}/{r['n']} "
              f"({r['percentile']:.1f}th percentile)")

    # drivers for SVB
    svb = next((r for r in rows if r["cert"] == 24735), None)
    if svb:
        d = score_vector(card, svb["features"])
        print(f"\n  Why SVB scores {d['risk_score']:.3f} — top drivers:")
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
