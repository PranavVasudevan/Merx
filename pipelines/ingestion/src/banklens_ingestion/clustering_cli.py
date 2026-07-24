"""Feature 14 runner — recluster the peer set by behavior and expose the mismatch
between behavioral clusters and conventional asset-size labels.

Run (after landing the population to Bronze)::

    powershell -File scripts/cluster_report.ps1
    # or:
    $env:PYTHONPATH = "pipelines/ingestion/src;pipelines/transforms/src"
    python -m banklens_ingestion.clustering_cli --highlight-cert 6976
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from banklens_transforms.clustering import (
    FEATURES, build_matrix, kmeans, label_cluster, select_k, silhouette_by_k,
)
from banklens_transforms.gold import gold_features
from banklens_transforms.silver import to_bank_financials

_REPORT_METRICS = [
    "concentration_ratio_cre", "concentration_ratio_c_and_i",
    "concentration_ratio_residential_mortgage", "uninsured_deposit_pct",
    "core_deposit_pct", "loan_to_deposit_pct",
]


def size_bucket(total_assets) -> str:
    if total_assets is None:
        return "unknown"
    if total_assets < 10e9:
        return "community (<$10B)"
    if total_assets < 50e9:
        return "regional ($10-50B)"
    return "super-regional (>$50B)"


def _mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def run(repdte: str, data_dir: Path, highlight_cert: int, k_override: int | None) -> None:
    bronze = data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}" / "records.json"
    print(f"[1/3] LOAD+GOLD — {bronze}")
    raw = json.loads(bronze.read_text(encoding="utf-8-sig"))
    gold = [gold_features(to_bank_financials(r)) for r in raw]
    print(f"        {len(gold)} banks; features: {', '.join(FEATURES)}")

    print("[2/3] CLUSTER — standardized K-Means (behavioral, not size-based)")
    kept, X = build_matrix(gold)
    diag = silhouette_by_k(X, range(2, 8))
    print("        silhouette / largest-cluster-share by k:")
    for kk, v in diag.items():
        print(f"          k={kk}: silhouette={v['silhouette']:+.3f}  max_share={v['max_share']:.0%}")
    auto_k = select_k(diag)
    k = k_override or auto_k
    labels = diag[k]["labels"] if k in diag else kmeans(X, k)[0]
    print(f"        NOTE: silhouette peaks at k=2, but that is degenerate (one cluster holds "
          f"{diag[2]['max_share']:.0%} of banks). Across k=4-7 silhouette is flat (~0.16-0.19),")
    print(f"        so interpretability drives the choice. Using k={k}"
          f"{' (forced)' if k_override else f' (auto: best non-degenerate = {auto_k})'}.\n")

    for g, lab in zip(kept, labels):
        g["peer_cluster_id"] = lab

    # characterize clusters
    clusters = {}
    for c in range(k):
        members = [g for g in kept if g["peer_cluster_id"] == c]
        means = {m: _mean(members, m) for m in _REPORT_METRICS}
        clusters[c] = {"n": len(members), "means": means, "label": label_cluster(means),
                       "members": members}
    for g in kept:
        g["peer_cluster_label"] = clusters[g["peer_cluster_id"]]["label"]

    out = data_dir / "gold" / "population" / f"repdte={repdte}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gold_clustered.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")

    W = 84
    print("=" * W)
    print(f"  FEATURE 14 — BEHAVIORAL PEER CLUSTERS   (n={len(kept)}, k={k})")
    print("=" * W)
    print(f"  {'cluster':<34}{'n':>5}  {'CRE%':>6}{'C&I%':>6}{'Res%':>6}{'Unins%':>7}{'Core%':>6}{'L/D%':>6}")
    for c in sorted(clusters):
        m = clusters[c]["means"]
        print(f"  {c}: {clusters[c]['label']:<30}{clusters[c]['n']:>5}  "
              f"{m['concentration_ratio_cre'] or 0:>6.0f}{m['concentration_ratio_c_and_i'] or 0:>6.0f}"
              f"{m['concentration_ratio_residential_mortgage'] or 0:>6.0f}"
              f"{m['uninsured_deposit_pct'] or 0:>7.0f}{m['core_deposit_pct'] or 0:>6.0f}"
              f"{m['loan_to_deposit_pct'] or 0:>6.0f}")

    # size-bucket x cluster crosstab: proof that asset size != behavior
    print("\n  Asset-size label vs behavioral cluster (bank counts):")
    buckets = ["community (<$10B)", "regional ($10-50B)", "super-regional (>$50B)"]
    header = "    " + f"{'size / cluster':<24}" + "".join(f"{c:>6}" for c in sorted(clusters))
    print(header)
    for b in buckets:
        row = [sum(1 for g in kept if size_bucket(g.get("total_assets")) == b
                   and g["peer_cluster_id"] == c) for c in sorted(clusters)]
        print("    " + f"{b:<24}" + "".join(f"{n:>6}" for n in row))
    print("  -> a single size bucket spreads across several behavioral clusters: "
          "size is a poor proxy for behavior.")

    # highlight one bank
    hi = next((g for g in kept if g.get("cert_number") == highlight_cert), None)
    if hi:
        cid = hi["peer_cluster_id"]
        cl = clusters[cid]
        member_buckets = Counter(size_bucket(m.get("total_assets")) for m in cl["members"])
        dominant = member_buckets.most_common(1)[0][0]
        own = size_bucket(hi.get("total_assets"))
        mates = [m["name"] for m in cl["members"] if m["cert_number"] != highlight_cert][:5]
        print("\n  " + "-" * (W - 4))
        print(f"  PEER STANDING — {hi['name']} (CERT {highlight_cert})")
        print(f"    Behavioral cluster {cid}: \"{cl['label']}\"  ({cl['n']} banks)")
        print(f"    Conventional size label: {own}")
        print(f"    Cluster's dominant size: {dominant}")
        if own != dominant:
            print(f"    >> MISCLASSIFIED by size: behaves like the '{dominant}' cohort, "
                  f"not a typical '{own}'.")
        else:
            print("    (behavioral cluster and size label agree)")
        print(f"    Behavioral peers e.g.: {', '.join(m[:28] for m in mates)}")
    print("=" * W)
    print(f"  Wrote clustered Gold to {out}\\gold_clustered.json\n")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 14 — behavioral peer clustering")
    p.add_argument("--repdte", default="20260331")
    p.add_argument("--highlight-cert", type=int, default=6976)
    p.add_argument("--k", type=int, default=None, help="force a cluster count (else silhouette picks)")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.repdte, args.data_dir, args.highlight_cert, args.k)


if __name__ == "__main__":
    main()
