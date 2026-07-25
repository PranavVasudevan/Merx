"""Feature 13 tests — the logistic-regression engine (hermetic) and the feature/
scoring helpers. The full train+validate-on-real-failures run is the CLI/showcase.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.deposit_flight import features_from, score_vector  # noqa: E402
from banklens_transforms.logreg import LogisticRegression, auc, sigmoid  # noqa: E402


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


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
