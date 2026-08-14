"""Feature 14 (C3) runner — fit behavioral-cluster centroids ONCE on a reference
quarter and persist them, so multi-quarter views (trends, briefing, migrations)
can assign every other quarter to the SAME fixed centroids instead of `population()`
independently refitting k-means every quarter — which flips a boundary bank's
cluster label on refit noise alone, even with stable-cluster-id label matching.

Per-quarter refit stays the default in `population()`/`/clusters` for exactly the
comparison this enables: run this once, then `get_quarterly_briefing`'s
`cluster_migrations` reports how many refit-apparent "migrations" don't occur
under fixed centroids.

    powershell -File scripts/cluster_centroids.ps1
    python -m banklens_ingestion.cluster_centroids_cli --repdte 20250630
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.clustering import fit_fixed_centroids, save_fixed_centroids
from banklens_transforms.gold import gold_features
from banklens_transforms.silver import to_bank_financials


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_landed(partition_dir: Path) -> Path:
    snaps = sorted(p for p in partition_dir.glob("landed=*") if (p / "records.json").exists())
    if not snaps:
        raise FileNotFoundError(f"No landed=* snapshot under {partition_dir}")
    return snaps[-1] / "records.json"


def _latest_repdte(data_dir: Path) -> str:
    pop_dir = data_dir / "bronze" / "source=fdic" / "population"
    found = sorted((p.name.split("=", 1)[1] for p in pop_dir.glob("repdte=*")
                    if p.is_dir() and any(p.glob("landed=*/records.json"))), reverse=True)
    if not found:
        raise FileNotFoundError(f"no landed population quarters under {pop_dir}")
    return found[0]


def run(data_dir: Path, repdte: str | None) -> None:
    repdte = repdte or _latest_repdte(data_dir)
    recs = _load(_latest_landed(data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}"))
    gold = [gold_features(to_bank_financials(r)) for r in recs]

    fit = fit_fixed_centroids(gold)
    save_fixed_centroids(fit, reference_quarter=repdte)

    print("=" * 78)
    print("  FEATURE 14 — FIXED CLUSTER CENTROIDS (C3)")
    print(f"  Reference quarter: {repdte}  (n={len(gold)} US banks, k={fit['k']})")
    print("=" * 78)
    for sid in fit["stable_ids"]:
        print(f"    cluster {sid:>2}  {fit['cluster_labels'][sid]}")
    print(f"\n  Saved to ml/clustering/fixed_centroids.json. Every other landed quarter's")
    print(f"  population() call with cluster_mode='fixed' now assigns to THESE centroids")
    print(f"  instead of refitting k-means from scratch.")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 14 — fixed cluster centroids")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    p.add_argument("--repdte", type=str, default=None,
                   help="Reference REPDTE (YYYYMMDD); defaults to the latest landed quarter.")
    args = p.parse_args()
    run(args.data_dir, args.repdte)


if __name__ == "__main__":
    main()
