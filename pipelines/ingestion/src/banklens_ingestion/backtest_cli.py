"""Feature 17 (C14) runner — backtests three signals (X-Ray high/elevated
risk, deposit-flight top-decile score, filing-diff any-flag) against every
consecutive pair of landed analytical quarters: did flagged banks
subsequently show deposit outflows, capital deterioration, credit
deterioration, or failure/exit from the population, more often than the rest
of the population? Pools raw hit/n counts across ALL available quarter
transitions (banklens_transforms.backtest.pool_backtest_results) before
computing the final confidence interval — a single quarter's flagged set is
too small to trust alone; B1's history backfill is what makes pooling here
meaningful.

Builds Silver/Gold directly from Bronze (like deposit_flight_cli/
ma_weights_cli/filing_diff_population_cli), NOT via banklens_mcp.data.
population() — that pipeline also runs k-means clustering per quarter, which
this harness doesn't need (cluster_migration is tracked as an outcome, but a
backtest doesn't need to recompute clusters to test THAT signal; the outcome
is simply left uncomputed here — n=0, surfaced honestly rather than paying
for 20 quarters of k-means to populate one of five outcome columns).

    powershell -File scripts/backtest.ps1
    python -m banklens_ingestion.backtest_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.backtest import backtest_signal, pool_backtest_results
from banklens_transforms.data_quality import capital_basis, exclusion_for
from banklens_transforms.deposit_flight import features_from, load_card, score_vector
from banklens_transforms.filing_diff import build_quarters, diff
from banklens_transforms.gold import gold_features
from banklens_transforms.silver import to_bank_financials
from banklens_transforms.xray import evaluate_xray

RESULT_PATH = Path(__file__).resolve().parents[4] / "ml" / "backtest" / "results.json"
_TRAINING_ONLY_QUARTERS = {"20221231", "20080331"}


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_landed(partition_dir: Path) -> Path | None:
    snaps = sorted(p for p in partition_dir.glob("landed=*") if (p / "records.json").exists())
    return (snaps[-1] / "records.json") if snaps else None


def _load_repdtes(pop_dir: Path) -> list[str]:
    return sorted(
        (p.name.split("=", 1)[1] for p in pop_dir.glob("repdte=*")
         if p.is_dir() and p.name.split("=", 1)[1] not in _TRAINING_ONLY_QUARTERS))


def run(data_dir: Path, top_decile_pct: float = 10.0) -> None:
    pop_dir = data_dir / "bronze" / "source=fdic" / "population"
    repdtes = _load_repdtes(pop_dir)   # oldest first
    if len(repdtes) < 2:
        raise RuntimeError(f"Need >= 2 landed analytical quarters under {pop_dir}, found {len(repdtes)}.")

    failures_path = data_dir / "bronze" / "source=fdic" / "failures" / "records.json"
    failed_certs: set[int] = set()
    if failures_path.exists():
        for f in _load(failures_path):
            if f.get("RESTYPE") == "FAILURE" and f.get("CERT") is not None:
                failed_certs.add(int(f["CERT"]))
    card = load_card()

    # Silver per quarter, oldest-first per cert (what build_quarters/diff and
    # gold_features' `history` argument both expect).
    silver_by_quarter: dict[str, dict[int, dict]] = {}
    history_by_cert: dict[int, list[dict]] = {}
    for repdte in repdtes:
        path = _latest_landed(pop_dir / f"repdte={repdte}")
        if path is None:
            continue
        quarter_silver: dict[int, dict] = {}
        for r in _load(path):
            s = to_bank_financials(r)
            if exclusion_for(s) is not None:      # non-deposit-funded — see data_quality
                continue
            cert = s.get("cert_number")
            if cert is None:
                continue
            quarter_silver[cert] = s
            history_by_cert.setdefault(cert, []).append(s)
        silver_by_quarter[repdte] = quarter_silver

    print(f"  {len(repdtes)} landed quarters, {len(history_by_cert)} distinct banks")

    signals: dict[str, list[dict]] = {
        "xray_high_risk": [], "deposit_flight_top_decile": [], "filing_diff_flagged": []}

    for i in range(len(repdtes) - 1):
        q_before, q_after = repdtes[i], repdtes[i + 1]
        before_silver, after_silver = silver_by_quarter[q_before], silver_by_quarter[q_after]
        prior_before_silver = silver_by_quarter.get(repdtes[i - 1]) if i > 0 else None

        # Merge Silver + Gold (same pattern as filing_diff.build_quarters) so
        # outcome functions can read either raw balance-sheet fields
        # (total_deposits — Silver only, Gold deliberately carries only
        # DERIVED ratios) or Gold ratios (cet1_ratio, deterioration_flag) from
        # one dict without the caller needing to know which layer a field
        # lives in.
        before_gold: dict[int, dict] = {}
        for cert, s in before_silver.items():
            hist = [row for row in history_by_cert[cert] if row["quarter"] <= s["quarter"]][::-1]
            before_gold[cert] = {**s, **gold_features(
                s, prior_before_silver.get(cert) if prior_before_silver else None, hist)}
        after_gold: dict[int, dict] = {}
        for cert, s in after_silver.items():
            hist = [row for row in history_by_cert[cert] if row["quarter"] <= s["quarter"]][::-1]
            after_gold[cert] = {**s, **gold_features(s, before_silver.get(cert), hist)}

        population_certs = set(before_gold)

        # -- X-Ray signal --
        xray_flagged = set()
        for cert, g in before_gold.items():
            basis = capital_basis(before_silver[cert])
            xr = evaluate_xray(g, capital_basis=basis)
            if xr["overall_risk"] in ("elevated", "high"):
                xray_flagged.add(cert)

        # -- Deposit-flight signal (top decile by score, this quarter) --
        dflight_flagged = set()
        if card is not None:
            idx4 = i - 4
            prior_dep_q = repdtes[idx4] if idx4 >= 0 else None
            scored = []
            for cert, s in before_silver.items():
                prior_dep = (silver_by_quarter.get(prior_dep_q, {}).get(cert, {}).get("total_deposits")
                            if prior_dep_q else None)
                feats = features_from(s, before_gold[cert], prior_dep)
                scored.append((cert, score_vector(card, feats)["risk_score"]))
            scored.sort(key=lambda t: t[1], reverse=True)
            cutoff = max(1, int(len(scored) * top_decile_pct / 100))
            dflight_flagged = {c for c, _ in scored[:cutoff]}

        # -- Filing-diff signal (any flag, this bank's own history thru q_before) --
        fdiff_flagged = set()
        for cert, s in before_silver.items():
            hist = [row for row in history_by_cert[cert] if row["quarter"] <= s["quarter"]][::-1]
            if len(hist) < 2:
                continue
            d = diff(build_quarters(hist))
            if d["n_flags"] > 0:
                fdiff_flagged.add(cert)

        signals["xray_high_risk"].append(
            backtest_signal(xray_flagged, population_certs, before_gold, after_gold, failed_certs))
        signals["deposit_flight_top_decile"].append(
            backtest_signal(dflight_flagged, population_certs, before_gold, after_gold, failed_certs))
        signals["filing_diff_flagged"].append(
            backtest_signal(fdiff_flagged, population_certs, before_gold, after_gold, failed_certs))

        print(f"  {q_before} -> {q_after}: xray={len(xray_flagged)} "
              f"dflight={len(dflight_flagged)} fdiff={len(fdiff_flagged)} flagged "
              f"of {len(population_certs)}")

    pooled = {name: pool_backtest_results(per_q) for name, per_q in signals.items()}
    payload = {
        "quarters_covered": repdtes,
        "n_transitions": len(repdtes) - 1,
        "horizon_quarters": 1,
        "signal_definitions": {
            "xray_high_risk": "X-Ray overall_risk in {elevated, high} at quarter t",
            "deposit_flight_top_decile": f"Deposit-flight risk_score in the top {top_decile_pct}% at quarter t"
                                        + (" (model not trained — empty)" if card is None else ""),
            "filing_diff_flagged": "filing_diff.diff() found >= 1 flagged line item vs quarter t-1",
        },
        "results": pooled,
        "note": (
            "Pooled across every consecutive quarter transition available. A lift near 1.0 or a "
            "confidence interval that straddles it means no detectable signal at this horizon with "
            "this sample — reported as a real, publishable finding, not hidden. cluster_migration "
            "is not computed by this harness (it doesn't run the k-means clustering pipeline) — "
            "n=0 there is a scope statement, not a null result."
        ),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 78)
    for name, outcomes in pooled.items():
        print(f"  {name}:")
        for key, o in outcomes.items():
            if o["base_n"] == 0:
                print(f"    {key:<24} no data")
                continue
            print(f"    {key:<24} flagged {o['flagged_hit_rate']['point']} "
                  f"(n={o['flagged_n']})  base {o['base_hit_rate']['point']} (n={o['base_n']})  "
                  f"lift {o['lift']}")
    print(f"  Saved to {RESULT_PATH.relative_to(data_dir.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 17 (C14) — backtest harness")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    p.add_argument("--top-decile-pct", type=float, default=10.0)
    args = p.parse_args()
    run(args.data_dir, args.top_decile_pct)


if __name__ == "__main__":
    main()
