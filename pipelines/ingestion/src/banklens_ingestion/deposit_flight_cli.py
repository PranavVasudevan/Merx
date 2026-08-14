"""Feature 13 runner — train the deposit-flight model on a POOLED cross-section
spanning two real financial crises (2022Q4 -> every real 2023 bank failure,
2008Q1 -> every real 2008 bank failure), validate against real history, and
save the model card.

Positives are landed from FDIC's own `failures` endpoint (docs/audit/
04-remediation-prompts.md B6), not hand-typed — see `derive_positive_certs`.
This now surfaces every real failure in each crisis year that was present in
that quarter's landed population (dozens, not the four best-known cases:
SVB/Signature/First Republic were the ONLY significant 2023 failures, but
2008 alone had ~25), not a name someone remembered to add.

    powershell -File scripts/deposit_flight.ps1
    python -m banklens_ingestion.deposit_flight_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.data_quality import summarize
from banklens_transforms.deposit_flight import (
    EXCLUDED_CANDIDATES, bootstrap_stats, build_rows, calibration_curve,
    cv_select_l2, derive_positive_certs, era_standardization_report,
    imputation_rates, leave_one_out, pr_curve, save_card, score_vector, train,
)

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.fdic import FdicSource


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_landed(partition_dir: Path) -> Path:
    """Bronze is append-only (B9): `population/repdte=X/landed=Y/records.json`
    can hold more than one snapshot per REPDTE. Pick the newest landing, same
    convention as `banklens_mcp.data._pop_snapshot_path`."""
    snaps = sorted(p for p in partition_dir.glob("landed=*") if (p / "records.json").exists())
    if not snaps:
        raise FileNotFoundError(f"No landed=* snapshot under {partition_dir}")
    return snaps[-1] / "records.json"


def _load_population(data_dir: Path, repdte: str) -> list[dict]:
    return _load(_latest_landed(data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}"))


def _prior_deposits(data_dir: Path, repdte: str) -> dict[int, float]:
    # This partition predates the point-in-time landed=* layout (B9) and is
    # still flat (repdte=X/records.json) — try that first, fall back to the
    # landed=* convention in case it's ever re-landed under the new layout.
    d = data_dir / "bronze" / "source=fdic" / "deposits" / f"repdte={repdte}"
    flat = d / "records.json"
    recs = _load(flat) if flat.exists() else _load(_latest_landed(d))
    return {int(r["CERT"]): float(r["DEP"]) * 1000 for r in recs if r.get("DEP") is not None}


def _land_failures(data_dir: Path) -> list[dict]:
    """Every FDIC bank failure on record, landed fresh each run (one keyless
    request, 4,000-ish rows — cheap enough not to bother caching to a separate
    step). See `sources/fdic.py.FdicSource.fetch_failures`."""
    src = FdicSource()
    rows, url = src.fetch_failures()
    prov = Provenance.create(source=src.name, endpoint=url, license=src.license, payload=rows)
    write_partition(rows, prov, base_dir=data_dir / "bronze", source="fdic", parts=("failures",))
    return rows


def run(data_dir: Path) -> None:
    print("Landing FDIC bank failures...")
    failures = _land_failures(data_dir)
    print(f"  {len(failures)} failures on record")

    # 2022Q4 cross-section (pre-2023-failures), paired with 2021Q4 deposits for growth.
    # `era` (C2) tags every row with which crisis it belongs to — "2023" here
    # matches the `fail_years` label just below, not the REPDTE (2022Q4).
    recs22 = _load_population(data_dir, "20221231")
    rows_2022, exc_2022 = build_rows(recs22, _prior_deposits(data_dir, "20211231"))
    for r in rows_2022:
        r["era"] = "2023"
    positives_2022 = derive_positive_certs(
        failures, {r["cert"] for r in rows_2022}, fail_years={"2023"})

    # 2008Q1 cross-section (pre-IndyMac-failure), paired with 2007Q1 deposits.
    recs08 = _load_population(data_dir, "20080331")
    rows_2008, exc_2008 = build_rows(recs08, _prior_deposits(data_dir, "20070331"))
    for r in rows_2008:
        r["era"] = "2008"
    positives_2008 = derive_positive_certs(
        failures, {r["cert"] for r in rows_2008}, fail_years={"2008"})

    positive_certs = {**positives_2022, **positives_2008}
    excluded_from_positives = []
    for cert, info in EXCLUDED_CANDIDATES.items():
        if positive_certs.pop(cert, None) is not None:
            excluded_from_positives.append((cert, info))
    if not positive_certs:
        raise RuntimeError(
            "derive_positive_certs found zero real positives from the landed FDIC "
            "failures data — the training population or fail_years filter likely "
            "needs adjusting; refusing to train on an empty positive set.")

    rows = rows_2022 + rows_2008
    exclusions = exc_2022 + exc_2008

    # C2 — select l2 by CV rather than the old hardcoded 1.0, and measure
    # whether the two pooled crisis eras need their own standardization.
    print("Running L2 cross-validation sweep...")
    l2_sweep = cv_select_l2(rows, positive_certs)
    selected_l2 = l2_sweep["selected_l2"]
    sweep_summary = ", ".join(f"{c['l2']}={c['mean_cv_auc']}" for c in l2_sweep["candidates"])
    print(f"  selected l2={selected_l2} (CV AUC by candidate: {sweep_summary})")

    print("Comparing pooled vs. per-era standardization...")
    era_report = era_standardization_report(rows, positive_certs, l2=selected_l2)
    print(f"  pooled CV AUC={era_report.get('pooled_cv_auc')}  "
          f"per-era CV AUC={era_report.get('per_era_cv_auc')}  "
          f"-> {era_report.get('decision')}")
    use_era_std = era_report.get("decision") == "per_era"
    # "2023" (the more contemporary cohort) is the scoring era for live,
    # current-quarter banks whose own era is otherwise unknown.
    scoring_era = "2023" if use_era_std else None

    card, fit = train(rows, trained_on="2022Q4 + 2008Q1", positive_certs=positive_certs,
                       l2=selected_l2, use_era_standardization=use_era_std,
                       scoring_era=scoring_era)
    card["l2_sweep"] = l2_sweep
    card["era_handling"] = era_report
    card["exclusions"] = summarize(exclusions, len(rows) + len(exclusions))
    # Persisted at train time, not recomputed per-request: leave_one_out retrains
    # the model once per positive (dozens, once B6 landed real failures), which
    # is fine for a one-off CLI run but not something a /model page load should
    # pay for on every request.
    card["leave_one_out"] = leave_one_out(rows, positive_certs=positive_certs,
                                           l2=selected_l2, use_era_standardization=use_era_std,
                                           scoring_era=scoring_era)
    # C1 — honest statistics, computed once at train time and persisted so /model
    # doesn't pay for a repeated bootstrap on every page load. Do NOT claim the
    # model is validated; the point is to show precisely how uncertain it is.
    card["imputation_rates"] = imputation_rates(rows)
    card["bootstrap"] = bootstrap_stats(rows, positive_certs, l2=selected_l2)
    card["pr_curve"] = pr_curve(fit["y"], fit["scores"])
    card["calibration_curve"] = calibration_curve(fit["y"], fit["scores"])
    save_card(card)

    W = 84
    print("=" * W)
    print("  FEATURE 13 — DEPOSIT-FLIGHT EARLY-WARNING")
    print(f"  Pooled training: 2022Q4 (n={len(rows_2022)}) + 2008Q1 (n={len(rows_2008)}) = {len(rows)}")
    print("=" * W)
    print(f"  Positives (real failures, landed from FDIC's own `failures` endpoint, "
          f"both crises): {', '.join(positive_certs.values())}")
    for cert, info in excluded_from_positives:
        print(f"  Excluded (found by the data-driven query, then filtered out): "
              f"{info['name']} (CERT {cert}) — {info['reason']}")

    exc = card["exclusions"]
    print(f"\n  Data-quality exclusions: {exc['excluded_count']} of {exc['total_considered']} "
          f"({exc['excluded_pct']}%) — deposits under {exc['threshold_pct']}% of assets, i.e. "
          f"not deposit-funded banks:")
    for e in exc["excluded"][:6]:
        print(f"    CERT {e['cert']:>6}  {e['deposits_to_assets_pct']:>7.3f}% dep/assets  "
              f"{(e['name'] or '')[:44]}")
    if exc["excluded_count"] > 6:
        print(f"    ... and {exc['excluded_count'] - 6} more (all listed in the model card)")
    print(f"  -> loan_to_deposit_pct imputation mean is now "
          f"{card['impute_means']['loan_to_deposit_pct']:,.2f}% "
          f"(it was 7,846.88% when these were pooled in, which flattened the feature to noise)")

    print(f"\n  In-sample ROC-AUC: {card['auc']}  "
          f"(bootstrap 95% CI [{card['bootstrap']['auc']['lo']}, {card['bootstrap']['auc']['hi']}], "
          f"{card['bootstrap']['n_boot_used']}/{card['bootstrap']['n_boot']} resamples usable)")
    print("\n  Coefficients (standardized; + raises modeled run-risk; bootstrap 95% CI):")
    for f, w in sorted(zip(card["features"], card["weights"], strict=True), key=lambda t: abs(t[1]), reverse=True):
        ci = card["bootstrap"]["coefficients"][f]
        print(f"    {f:<24} {w:+.3f}   CI [{ci['lo']}, {ci['hi']}]   "
              f"imputed {card['imputation_rates'][f]}%")

    # rank everyone; where do the actual failures land?
    scored = sorted(((r["cert"], r["name"], score_vector(card, r["features"], era=r.get("era"))["risk_score"])
                     for r in rows), key=lambda t: t[2], reverse=True)
    print("\n  Riskiest banks by the model (top 8, both eras pooled):")
    for i, (c, n, s) in enumerate(scored[:8], 1):
        mark = "  <== ACTUAL FAILURE" if c in positive_certs else ""
        print(f"    {i:>2}. {s:.3f}  {(n or '')[:40]:<40}{mark}")

    print("\n  HONEST TEST — leave-one-out (retrain WITHOUT the bank, then score it "
          f"against the FULL pooled universe of all {len(rows)} banks, both eras):")
    # Reuses card["leave_one_out"] (computed once, above) rather than calling
    # leave_one_out() again — with 4 hardcoded positives a second retrain-per-
    # positive pass was cheap to not bother caching; landed data (B6) can
    # surface dozens of real positives (every bank that failed in a landed
    # crisis year, not just the four best-known ones), and retraining twice
    # per positive at that count is minutes of wasted compute for a printout.
    for r in card["leave_one_out"]:
        print(f"    {r['name']:<20} risk {r['risk']:.3f}  -> rank {r['rank']}/{r['n']} "
              f"({r['percentile']:.1f}th percentile)")

    # drivers for SVB and IndyMac — the two most contrasting cases
    for cert, label in ((24735, "SVB"), (29730, "IndyMac")):
        target = next((r for r in rows if r["cert"] == cert), None)
        if target:
            d = score_vector(card, target["features"], era=target.get("era"))
            print(f"\n  Why {label} scores {d['risk_score']:.3f} — top drivers:")
            for drv in d["drivers"][:3]:
                print(f"    {drv['feature']:<24} = {drv['value']:>8}  (log-odds {drv['contribution']:+.2f})")
    print("=" * W)
    print("  Model card saved. In-sample AUC and leave-one-out are the honest checks.")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 13 — deposit-flight model")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
