"""Feature 13 tests — the logistic-regression engine and feature/scoring helpers
(hermetic), plus the **backtest as a CI test** against the real landed crisis data.

The architecture plan names "backtest-as-CI-test" as the mitigation for its own
top-listed model risk ("feature 13 looks impressive but leaks"), and until now that
test did not exist — every test here was synthetic. `test_backtest_svb_*` closes that:
it retrains with SVB removed from the training set entirely and asserts the model
still ranks SVB near the top of the pooled universe. If a future change silently
breaks the model's ability to catch a real failure, this goes red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.data_quality import deposit_funding_pct, exclusion_for, partition  # noqa: E402
from banklens_transforms.deposit_flight import (  # noqa: E402
    build_rows, features_from, score_vector, train,
)
from banklens_transforms.logreg import LogisticRegression, auc  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
SVB_CERT = 24735


class SkipTest(Exception):
    """Needs landed crisis data. `data/` is git-ignored and reproducible from the
    landing scripts, so a fresh clone legitimately won't have it — that's a SKIP."""


def _load_pooled_training_rows():
    """The real pooled 2022Q4 + 2008Q1 cross-sections the model actually trains on."""
    base = REPO / "data" / "bronze" / "source=fdic"
    pairs = [("20221231", "20211231"), ("20080331", "20070331")]
    rows, exclusions = [], []
    for repdte, prior in pairs:
        pop = base / "population" / f"repdte={repdte}" / "records.json"
        dep = base / "deposits" / f"repdte={prior}" / "records.json"
        if not pop.exists() or not dep.exists():
            raise SkipTest(f"no landed crisis data at {pop} (run the landing scripts)")
        recs = json.loads(pop.read_text(encoding="utf-8-sig"))
        prior_dep = {int(r["CERT"]): float(r["DEP"]) * 1000
                     for r in json.loads(dep.read_text(encoding="utf-8-sig"))
                     if r.get("DEP") is not None}
        r, e = build_rows(recs, prior_dep)
        rows += r
        exclusions += e
    return rows, exclusions


def test_logreg_separates_linearly_separable():
    # positives have large x0; negatives small
    X = [[3.0, 0.1], [2.5, 0.0], [3.2, -0.1]] + [[-2.0, 0.0], [-2.5, 0.1], [-3.0, -0.2]]
    y = [1, 1, 1, 0, 0, 0]
    m = LogisticRegression(l2=0.1, epochs=2000).fit(X, y)
    probs = m.predict_proba(X)
    assert min(probs[:3]) > 0.5 and max(probs[3:]) < 0.5
    assert m.w[0] > 0                       # positive class has high x0


def test_auc_perfect_and_random():
    assert auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5


def test_features_from_computes_htm_to_equity():
    silver = {"total_equity": 100, "securities_htm": 590, "securities_total": 700,
              "total_assets": 2000, "total_deposits": 1000}
    gold = {"uninsured_deposit_pct": 86.0, "loan_to_deposit_pct": 42.0}
    f = features_from(silver, gold, prior_deposits_usd=900)
    assert f["htm_to_equity"] == 590.0
    assert round(f["securities_to_assets"], 1) == 35.0
    assert round(f["deposit_growth_1yr"], 2) == round((1000 - 900) / 900 * 100, 2)


def test_score_vector_monotonic_in_uninsured():
    # a hand-built card weighting only uninsured_deposit_pct
    card = {"features": ["uninsured_deposit_pct", "htm_to_equity", "securities_to_assets",
                         "loan_to_deposit_pct", "deposit_growth_1yr"],
            "impute_means": {k: 0.0 for k in ["uninsured_deposit_pct", "htm_to_equity",
                             "securities_to_assets", "loan_to_deposit_pct", "deposit_growth_1yr"]},
            "std_mu": [50, 100, 20, 80, 0], "std_sd": [20, 100, 10, 20, 30],
            "weights": [3.0, 0, 0, 0, 0], "bias": -1.0}
    low = score_vector(card, {"uninsured_deposit_pct": 30})["risk_score"]
    high = score_vector(card, {"uninsured_deposit_pct": 95})["risk_score"]
    assert high > low
    # top driver is uninsured
    assert score_vector(card, {"uninsured_deposit_pct": 95})["drivers"][0]["feature"] == "uninsured_deposit_pct"


# ---- data-quality policy (hermetic) --------------------------------------
def test_deposit_funding_pct_and_exclusion_rule():
    trust = {"cert_number": 90544, "name": "THE DEPOSITORY TRUST COMPANY",
             "total_assets": 8_000_000_000, "total_deposits": 0}
    bank = {"cert_number": 6976, "name": "DIME", "total_assets": 15_000_000_000,
            "total_deposits": 11_000_000_000}
    assert deposit_funding_pct(trust) == 0.0
    assert round(deposit_funding_pct(bank), 1) == 73.3
    assert exclusion_for(trust)["rule"] == "not_deposit_funded"
    assert exclusion_for(bank) is None


def test_unknown_funding_is_not_excluded():
    """We don't drop a bank on the basis of data we don't have."""
    assert exclusion_for({"cert_number": 1, "name": "X", "total_assets": None}) is None


def test_partition_preserves_order_and_splits():
    rows = [{"cert_number": 1, "name": "keep", "total_assets": 100, "total_deposits": 80},
            {"cert_number": 2, "name": "drop", "total_assets": 100, "total_deposits": 1},
            {"cert_number": 3, "name": "keep2", "total_assets": 100, "total_deposits": 50}]
    kept, exc = partition(rows)
    assert [k["cert_number"] for k in kept] == [1, 3]
    assert [e["cert"] for e in exc] == [2]


# ---- the backtest, against real landed data ------------------------------
def test_backtest_svb_is_flagged_without_being_trained_on():
    """THE headline claim, as a test: given only data available at 2022Q4, and with
    SVB removed from training entirely, does the model still surface SVB?

    Asserts top-5% of the pooled universe. Measured at the time of writing: rank
    33/1632 = 98.0th percentile. A regression that drops SVB out of the top 5% means
    the model has stopped detecting the archetype it exists to detect."""
    rows, _ = _load_pooled_training_rows()
    assert any(r["cert"] == SVB_CERT for r in rows), "SVB not in the landed training data"

    card, _ = train([r for r in rows if r["cert"] != SVB_CERT])
    scored = sorted(((r["cert"], score_vector(card, r["features"])["risk_score"])
                     for r in rows), key=lambda t: t[1], reverse=True)
    rank = next(i for i, (c, _) in enumerate(scored) if c == SVB_CERT) + 1
    pct = (1 - (rank - 1) / len(scored)) * 100
    assert pct >= 95.0, (
        f"SVB ranked {rank}/{len(scored)} = {pct:.1f}th percentile when trained without "
        f"it; the backtest requires >= 95th")


def test_backtest_training_excludes_non_deposit_funded_charters():
    """Regression guard for a REAL defect: pooling trust/clearing/card charters (which
    hold billions against ~zero deposits) drove loan_to_deposit_pct's imputation mean
    to 7,846.88% with sd 193,737, collapsing that feature to noise for every bank."""
    rows, exclusions = _load_pooled_training_rows()
    assert exclusions, "expected non-deposit-funded charters to be excluded"
    assert any(e["cert"] == 90544 for e in exclusions), "The Depository Trust Company must be excluded"

    card, _ = train(rows)
    ltd_mean = card["impute_means"]["loan_to_deposit_pct"]
    assert 50.0 < ltd_mean < 150.0, f"loan_to_deposit_pct imputation mean {ltd_mean:,.2f}% is not plausible"
    sd = card["std_sd"][card["features"].index("loan_to_deposit_pct")]
    assert sd < 1000.0, f"loan_to_deposit_pct std-dev {sd:,.1f} indicates outlier contamination"


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
