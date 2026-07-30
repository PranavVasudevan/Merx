"""Feature 15 runner — rank M&A partners for a target bank across the peer set.

    powershell -File scripts/ma_fit.ps1 -TargetCert 6976
    python -m banklens_ingestion.ma_fit_cli --target-cert 6976 --top-n 8

Geography uses REAL branch-level footprint from the FDIC Summary of Deposits,
grid-cell based (not state/county — FDIC's own STALP/CITY fields are unreliable at
branch level, verified live; see banklens_transforms.footprint). Needs
scripts/land_sod.ps1 to have landed the SOD Bronze data first.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.footprint import build_footprints
from banklens_transforms.gold import gold_features
from banklens_transforms.ma_fit import rank_partners
from banklens_transforms.silver import to_bank_financials


def _b(v) -> str:
    return "n/a" if v is None else f"${v/1e9:,.1f}B"


def run(repdte: str, data_dir: Path, sod_year: int, target_cert: int, top_n: int) -> None:
    bronze = data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}" / "records.json"
    raw = json.loads(bronze.read_text(encoding="utf-8-sig"))
    population = []
    for r in raw:
        s = to_bank_financials(r)
        m = dict(s)
        m.update(gold_features(s))
        population.append(m)

    sod_path = data_dir / "bronze" / "source=fdic" / "sod" / f"year={sod_year}" / "records.json"
    footprints = {}
    if sod_path.exists():
        footprints = build_footprints(json.loads(sod_path.read_text(encoding="utf-8-sig")))
    else:
        print(f"  (no SOD data at {sod_path} — geo overlap will be unavailable; "
              f"run scripts/land_sod.ps1 first)\n")

    target = next((b for b in population if b.get("cert_number") == target_cert), None)
    if target is None:
        print(f"  CERT {target_cert} not in the population slice.")
        return

    ranked = rank_partners(target, population, top_n=top_n, footprints=footprints)
    t_fp = footprints.get(target_cert)

    W = 88
    print("=" * W)
    print("  FEATURE 15 — M&A FIT FINDER")
    print(f"  Target: {target['name']}  (CERT {target_cert})")
    print("=" * W)
    branch_note = f"{t_fp['branch_count']} branches, {len(t_fp['cells'])} local market(s)" if t_fp else "no SOD data"
    print(f"    assets {_b(target.get('total_assets'))}   loan/deposit "
          f"{target.get('loan_to_deposit_pct')}%   CRE {target.get('concentration_ratio_cre')}%   "
          f"footprint: {branch_note}")
    print(f"\n  Top {top_n} partner candidates (fund=funding-complementarity, "
          f"sim=business-similarity, size, geo=real branch-network overlap):\n")
    print(f"  {'#':>2}  {'candidate':<38}{'fit':>6}{'fund':>6}{'sim':>6}{'size':>6}{'geo':>6}{'geo$':>6}")
    for i, r in enumerate(ranked, 1):
        geo = "-" if r["geo_overlap"] is None else f"{r['geo_overlap']:.2f}"
        geod = "-" if r["geo_overlap_deposit_weighted"] is None else f"{r['geo_overlap_deposit_weighted']:.2f}"
        print(f"  {i:>2}  {(r['name'] or '')[:36]:<38}{r['fit_score']:>6.2f}"
              f"{r['funding_complementarity']:>6.2f}{r['business_similarity']:>6.2f}"
              f"{r['size_fit']:>6.2f}{geo:>6}{geod:>6}")
    print("\n  Rationale for the top match:")
    if ranked:
        print(f"    {ranked[0]['name']}: {ranked[0]['rationale']}")
    print("=" * W)
    out = data_dir / "gold" / f"ma_fit.cert={target_cert}.json"
    out.write_text(json.dumps({"target": target_cert, "candidates": ranked}, indent=2),
                   encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 15 — M&A fit finder")
    p.add_argument("--repdte", default="20260331")
    p.add_argument("--sod-year", type=int, default=2025)
    p.add_argument("--target-cert", type=int, default=6976)
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.repdte, args.data_dir, args.sod_year, args.target_cert, args.top_n)


if __name__ == "__main__":
    main()
