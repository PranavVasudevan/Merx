"""Feature 14 (C10) runner — the cheapest genuine validation available for the
X-Ray rule engine: for every (bank, historical landed quarter) where BOTH an
X-Ray severity as of that quarter AND a subsequent Tiingo price bar
`horizon_days` later are landed, does high severity predict UNDERPERFORMANCE
relative to low severity? Published either way (banklens_transforms.market.
xray_severity_forward_returns's own instruction: a null result is as
reportable as a real one).

Needs Tiingo price data landed (the user's own free TIINGO_API_KEY — see
scripts/land_market_data.ps1); degrades to an honest zero-observation result,
not an error, if none is landed yet.

    powershell -File scripts/xray_validation.ps1
    python -m banklens_ingestion.xray_validation_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.data_quality import capital_basis
from banklens_transforms.gold import gold_features
from banklens_transforms.market import (
    forward_return_from, quarter_end_date, xray_severity_forward_returns,
)
from banklens_transforms.xray import evaluate_xray

# Unlike deposit_flight_cli/ma_weights_cli (pure pipelines/transforms + Bronze
# JSON), this reuses banklens_mcp.data for population()/bank_history()/
# ticker_for_cert()/price_bars() rather than re-implementing Bronze loading a
# third time — so PYTHONPATH needs services/mcp-server/src too (see
# scripts/xray_validation.ps1).
from banklens_mcp import data

RESULT_PATH = Path(__file__).resolve().parents[4] / "ml" / "xray" / "forward_return_validation.json"


def run(data_dir: Path, horizon_days: int = 63) -> None:
    pop = data.population()
    tickers_seen = set()
    observations: list[dict] = []
    quarters_used = set()

    for cert, silver in pop["silver_by_cert"].items():
        ticker = data.ticker_for_cert(cert)
        if not ticker:
            continue
        bars = data.price_bars(ticker)
        if not bars:
            continue
        tickers_seen.add(ticker)
        for hist_silver in data.bank_history(cert):
            q = hist_silver.get("quarter")
            end_date = quarter_end_date(q)
            if not end_date:
                continue
            fwd = forward_return_from(bars, end_date, horizon_days)
            if fwd is None:
                continue
            gold_row = gold_features(hist_silver)
            basis = capital_basis(hist_silver)
            xray = evaluate_xray(gold_row, capital_basis=basis)
            observations.append({
                "cert": cert, "quarter": q, "severity": xray["overall_risk"],
                "forward_return_pct": fwd,
            })
            quarters_used.add(q)

    result = xray_severity_forward_returns(observations)
    payload = {
        "horizon_trading_days": horizon_days,
        "tickers_with_landed_price_data": len(tickers_seen),
        "quarters_covered": sorted(quarters_used),
        **result,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"  Tickers with landed price data: {len(tickers_seen)}")
    print(f"  Observations (bank x quarter, X-Ray + forward return both available): "
          f"{result['n_total']}")
    if result["n_total"] == 0:
        print("  No observations — land Tiingo price data first "
              "(scripts/land_market_data.ps1, needs a free TIINGO_API_KEY).")
    else:
        for sev in ("low", "elevated", "high"):
            s = result["by_severity"][sev]
            print(f"  {sev:<10} n={s['n']:<5} mean forward return {s['mean']}%")
        print(f"  High vs low spread: {result['high_vs_low_spread_pp']}pp  "
              f"z={result['z_score']}  p={result['p_value']}  "
              f"significant@.05={result['significant_at_05']}")
    print(f"  Saved to {RESULT_PATH.relative_to(data_dir.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 14 (C10) — X-Ray forward-return validation")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    p.add_argument("--horizon-days", type=int, default=63)
    args = p.parse_args()
    run(args.data_dir, args.horizon_days)


if __name__ == "__main__":
    main()
