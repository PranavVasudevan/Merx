"""Feature 15 (C9) runner — validate `ma_fit.DEFAULT_WEIGHTS` against REAL deal
history instead of leaving them hand-set and untested: FDIC's own `failures`
endpoint (already landed for B6/deposit_flight) carries the ACQUIRING
institution (`BIDNAME`) for every FDIC-resolved failure, matched against the
SAME quarter's landed population to recover real (target, acquirer) cert
pairs (`ma_fit.match_deal_history`).

For each real deal, asks the honest question: does `fit_score` rank the REAL
acquirer near the top of every candidate for that target (like
deposit_flight's leave_one_out does for failure risk)? Reports the mean/
median acquirer percentile for `DEFAULT_WEIGHTS`, and a coarse grid-search
refit (`ma_fit.refit_weights`) over the same sample — publishing whichever
result is real, including "the default weights are about as good as a
refit" or "refitting doesn't clearly help" as valid, reportable outcomes.

    powershell -File scripts/ma_weights.ps1
    python -m banklens_ingestion.ma_weights_cli
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from banklens_transforms.gold import gold_features
from banklens_transforms.ma_fit import (
    DEFAULT_WEIGHTS, evaluate_weights, match_deal_history, refit_weights,
)
from banklens_transforms.silver import to_bank_financials

WEIGHT_VALIDATION_PATH = Path(__file__).resolve().parents[4] / "ml" / "ma_fit" / "weight_validation.json"


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_landed(partition_dir: Path) -> Path:
    snaps = sorted(p for p in partition_dir.glob("landed=*") if (p / "records.json").exists())
    if not snaps:
        raise FileNotFoundError(f"No landed=* snapshot under {partition_dir}")
    return snaps[-1] / "records.json"


def _gold_by_cert(data_dir: Path, repdte: str) -> dict[int, dict]:
    recs = _load(_latest_landed(data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}"))
    gold = [gold_features(to_bank_financials(r)) for r in recs]
    return {g["cert_number"]: g for g in gold if g.get("cert_number") is not None}


def _ranking_sample(by_cert: dict[int, dict], deals: list[dict], *,
                    max_size: int = 500, seed: int = 3) -> list[dict]:
    """`refit_weights`' grid search calls `_acquirer_percentile` once per
    (weight-combo x deal), and that ranks the real acquirer against EVERY
    candidate in the population — at ~8,500 banks in the 2008Q1 partition, a
    ~40-combo x 340-deal grid search would be ~800M `fit_score` calls (measured
    to be impractically slow in pure Python). This samples the ranking pool
    down to `max_size` instead: every deal's own target/acquirer certs are
    always included (so `_acquirer_percentile` can still find the real
    acquirer's score), padded out with a fixed-seed random sample of
    "distractor" candidates — still large enough for a meaningful percentile,
    not the full population. DEFAULT_WEIGHTS' own evaluation (the number that
    actually matters most, and runs only once) still uses the FULL population.
    """
    keep = {d["target_cert"] for d in deals} | {d["acquirer_cert"] for d in deals}
    pool = [c for c in by_cert if c not in keep]
    if len(pool) > max_size:
        pool = random.Random(seed).sample(pool, max_size)
    certs = keep | set(pool)
    return [by_cert[c] for c in certs]


def run(data_dir: Path) -> None:
    failures_path = data_dir / "bronze" / "source=fdic" / "failures" / "records.json"
    if not failures_path.exists():
        raise FileNotFoundError(
            f"{failures_path} not landed — run deposit_flight_cli first (it lands "
            "FDIC failures as a side effect) or scripts/deposit_flight.ps1.")
    failures = _load(failures_path)

    quarters = {"2022Q4": "20221231", "2008Q1": "20080331"}
    all_percentiles: list[float] = []
    per_quarter: dict[str, dict] = {}

    for label, repdte in quarters.items():
        by_cert = _gold_by_cert(data_dir, repdte)
        pop_list = list(by_cert.values())
        deals = match_deal_history(failures, by_cert)
        result = evaluate_weights(deals, by_cert, pop_list, weights=DEFAULT_WEIGHTS)
        per_quarter[label] = {"n_matched_deals": len(deals), **result}
        all_percentiles.extend(d["acquirer_percentile"] for d in result["deals"])
        print(f"  {label}: {len(deals)} matched deals, "
              f"mean acquirer percentile {result['mean_percentile']} (n={result['n']})")

    overall_mean = round(sum(all_percentiles) / len(all_percentiles), 1) if all_percentiles else None

    # Refit per quarter (grid search is O(weight-grid x deals x population) —
    # doing it once per quarter keeps each pass's population size manageable).
    refits = {}
    for label, repdte in quarters.items():
        by_cert = _gold_by_cert(data_dir, repdte)
        deals = match_deal_history(failures, by_cert)
        if not deals:
            continue
        sample = _ranking_sample(by_cert, deals)
        print(f"  {label}: refitting over a {len(sample)}-bank ranking sample "
              f"({len(deals)} deals)...")
        refits[label] = refit_weights(deals, by_cert, sample, step=0.2)
        print(f"  {label} refit: {refits[label]['weights']} -> "
              f"mean percentile {refits[label]['mean_percentile']}")

    # Deal-count-WEIGHTED comparison, DEFAULT vs REFIT on the SAME quarter's
    # SAME deals — not the naive "best single refit vs the pooled default
    # mean" comparison this originally did, which let a tiny 7-deal quarter's
    # refit (noisy, easy to beat the aggregate by chance) outvote the far
    # larger and more reliable 340-deal quarter. A quarter only contributes to
    # BOTH sums when it has a refit AND matched deals, so the two weighted
    # means are computed over the identical deal set.
    weighted_default_num = sum(per_quarter[label]["mean_percentile"] * per_quarter[label]["n_matched_deals"]
                               for label in refits if per_quarter[label]["mean_percentile"] is not None)
    weighted_refit_num = sum(refits[label]["mean_percentile"] * per_quarter[label]["n_matched_deals"]
                             for label in refits if refits[label].get("mean_percentile") is not None)
    weighted_n = sum(per_quarter[label]["n_matched_deals"] for label in refits)
    weighted_default_mean = round(weighted_default_num / weighted_n, 1) if weighted_n else None
    weighted_refit_mean = round(weighted_refit_num / weighted_n, 1) if weighted_n else None

    best_refit = max((r for r in refits.values() if r.get("mean_percentile") is not None),
                     key=lambda r: r["mean_percentile"], default=None)
    margin = 5.0  # percentile points — avoid flipping the decision on noise
    decision = "refit" if (weighted_refit_mean is not None and weighted_default_mean is not None
                           and weighted_refit_mean > weighted_default_mean + margin) else "default"

    payload = {
        "default_weights": DEFAULT_WEIGHTS,
        "overall_mean_percentile": overall_mean,
        "n_deals_total": len(all_percentiles),
        "per_quarter": per_quarter,
        "refit": refits,
        # Deal-count-weighted DEFAULT-vs-REFIT comparison across quarters that
        # have BOTH a default result and a refit — this, not
        # best_refit_mean_percentile, drives `decision`.
        "weighted_default_mean_percentile": weighted_default_mean,
        "weighted_refit_mean_percentile": weighted_refit_mean,
        "weighted_n": weighted_n,
        # Informational only — the single best-scoring weight combo across all
        # per-quarter refits, NOT what the decision is based on (a small-n
        # quarter can top this by chance; see weighted_* above).
        "best_refit_weights": best_refit["weights"] if best_refit else None,
        "best_refit_mean_percentile": best_refit["mean_percentile"] if best_refit else None,
        "margin_pp": margin,
        "decision": decision,
        "note": (
            f"decision='refit': the deal-count-weighted refit mean ({weighted_refit_mean}) beat "
            f"the weighted default mean ({weighted_default_mean}) by more than {margin} "
            f"percentile points across {weighted_n} real deals — adopted."
            if decision == "refit" else
            f"decision='default': the deal-count-weighted refit mean ({weighted_refit_mean}) did "
            f"not beat the weighted default mean ({weighted_default_mean}) by more than {margin} "
            f"percentile points across {weighted_n} real deals — kept the hand-set weights. "
            "The 2008Q1 quarter (340 matched deals) dominates this comparison and is far more "
            "reliable than 2022Q4's 7 deals; see per_quarter and refit for the quarter-level "
            "detail, including any single quarter where a refit did look better in isolation."
        ),
    }
    WEIGHT_VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHT_VALIDATION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"  Overall: {len(all_percentiles)} deals, mean acquirer percentile {overall_mean}")
    print(f"  Weighted default {weighted_default_mean} vs weighted refit {weighted_refit_mean} "
          f"(n={weighted_n}, margin {margin}pp)")
    print(f"  Decision: {decision}")
    print(f"  Saved to {WEIGHT_VALIDATION_PATH.relative_to(data_dir.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 15 — M&A weight validation")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
