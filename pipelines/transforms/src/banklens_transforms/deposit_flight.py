"""Feature 13 — Deposit-Flight Early-Warning (the showcase).

Classifies banks by structural resemblance to real bank-run cases. Trained on a
POOLED cross-section spanning two real financial crises 15 years apart — 2022Q4
(the quarter before the March-2023 failures: SVB, Signature, First Republic) and
2008Q1 (the quarter before IndyMac's July-2008 failure) — labeling the banks that
actually failed as positives, then validated against history: "trained WITHOUT
this bank, would it still have flagged it?" (leave-one-out), across BOTH crises.

Features (all computable from FDIC call-report fields):
  uninsured_deposit_pct   — depositors who run first (SVB ~86%)
  htm_to_equity           — held-to-maturity book vs capital; the unrealized-loss bomb (SVB ~591%)
  securities_to_assets    — rate-sensitive asset share
  loan_to_deposit_pct     — funding intensity
  deposit_growth_1yr      — hot-money growth / early outflow

Interpretability by coefficient contribution (value_z x weight), not a black box.

Pooling two eras is a deliberate, documented modeling choice: features are all
RATIOS (not absolute dollar levels), which is what makes a 2008 balance sheet and a
2022 one comparable at all — but the two eras still had different rate/macro
environments, and this is a hand-picked (not randomly sampled) universe. Treat this
as a real but limited-n showcase, not a rigorously cross-validated production model.

IndyMac is a genuinely DIFFERENT failure archetype from the 2023 cohort — worth
knowing before reading its leave-one-out result. Its 2008Q1 profile: uninsured
deposits ~13% (vs SVB's ~86%), HTM/equity ~0% (vs SVB's ~591%). IndyMac's failure was
driven primarily by subprime-mortgage credit losses, with a late-stage RETAIL
depositor panic (triggered by a public letter) as the proximate trigger — not the
uninsured-institutional-deposit-flight structural pattern the other three positives
share and the feature set is tuned to catch. Its most anomalous feature is instead
its deposit_growth_1yr (~+63% in the year before failure — rapid, hot-money-style
funding growth). Whether the model flags it well or poorly is an honest empirical
question, not something to assume either way — see the CLI's leave-one-out output.

Washington Mutual (also a real, famous 2008 depositor run — a ~$16.7B outflow in the
10 days before failure) is deliberately EXCLUDED, not forgotten: at ~$307B in assets
it exceeds this platform's $1B-$250B population band by a wide margin, and pooling
in a bank 10-60x larger than every other training example risks the model learning
size-correlated confounds that don't generalize back down to the population it will
actually score. A production build would either special-case a widened band for
historical-training data only, or source a separate large-bank cohort/model.
"""

from __future__ import annotations

import json
from pathlib import Path

from .gold import gold_features
from .logreg import LogisticRegression, auc, sigmoid
from .silver import to_bank_financials

FEATURES = ["uninsured_deposit_pct", "htm_to_equity", "securities_to_assets",
            "loan_to_deposit_pct", "deposit_growth_1yr"]

# Real deposit-run failures within the $1B-$250B population band, pooled across two
# crises (FDIC failures list, verified live): 2023 (trained on 2022Q4) + 2008 (trained
# on 2008Q1).
POSITIVE_CERTS = {24735: "Silicon Valley Bank", 57053: "Signature Bank",
                  59017: "First Republic Bank", 29730: "IndyMac Bank"}

# Documented, not silently dropped — see the module docstring for why each is excluded.
EXCLUDED_CANDIDATES = {
    32633: {"name": "Washington Mutual Bank", "reason":
            "assets ~$307B at failure (2008) — exceeds the $1B-$250B population band "
            "by 10-60x every other training example; would risk the model learning "
            "size confounds rather than structural risk signal."},
}

MODEL_CARD = Path(__file__).resolve().parents[4] / "ml" / "deposit_flight" / "model_card.json"


def features_from(silver: dict, gold: dict, prior_deposits_usd: float | None = None) -> dict:
    eq, htm = silver.get("total_equity"), silver.get("securities_htm")
    sc, assets = silver.get("securities_total"), silver.get("total_assets")
    dep = silver.get("total_deposits")
    return {
        "uninsured_deposit_pct": gold.get("uninsured_deposit_pct"),
        "htm_to_equity": (htm / eq * 100) if (htm is not None and eq and eq > 0) else None,
        "securities_to_assets": (sc / assets * 100) if (sc is not None and assets) else None,
        "loan_to_deposit_pct": gold.get("loan_to_deposit_pct"),
        "deposit_growth_1yr": ((dep - prior_deposits_usd) / prior_deposits_usd * 100)
        if (prior_deposits_usd and dep is not None) else None,
    }


def build_rows(records: list[dict], prior_dep_usd: dict[int, float]) -> list[dict]:
    rows = []
    for r in records:
        s = to_bank_financials(r)
        g = gold_features(s)
        cert = s.get("cert_number")
        rows.append({"cert": cert, "name": s.get("name"),
                     "features": features_from(s, g, prior_dep_usd.get(cert))})
    return rows


def _impute_means(rows: list[dict]) -> dict:
    means = {}
    for k in FEATURES:
        vals = [r["features"][k] for r in rows if r["features"].get(k) is not None]
        means[k] = sum(vals) / len(vals) if vals else 0.0
    return means


def _matrix(rows, means):
    X, y, certs, names = [], [], [], []
    for r in rows:
        X.append([r["features"][k] if r["features"].get(k) is not None else means[k]
                  for k in FEATURES])
        y.append(1 if r["cert"] in POSITIVE_CERTS else 0)
        certs.append(r["cert"]); names.append(r["name"])
    return X, y, certs, names


def _standardize(X):
    n, d = len(X), len(X[0])
    cols = list(zip(*X))
    mu = [sum(c) / n for c in cols]
    sd = [(sum((v - mu[j]) ** 2 for v in cols[j]) / n) ** 0.5 or 1.0 for j in range(d)]
    Xs = [[(X[i][j] - mu[j]) / sd[j] for j in range(d)] for i in range(n)]
    return Xs, mu, sd


def train(rows: list[dict], *, trained_on: str = "2022Q4") -> tuple[dict, dict]:
    means = _impute_means(rows)
    X, y, certs, names = _matrix(rows, means)
    Xs, mu, sd = _standardize(X)
    model = LogisticRegression(lr=0.2, epochs=2000, l2=1.0).fit(Xs, y)
    scores = model.predict_proba(Xs)
    card = {"features": FEATURES, "impute_means": means, "std_mu": mu, "std_sd": sd,
            "weights": model.w, "bias": model.b, "trained_on": trained_on,
            "positives": sorted(POSITIVE_CERTS), "auc": auc(y, scores)}
    return card, {"y": y, "certs": certs, "names": names, "scores": scores}


def score_vector(card: dict, feats: dict) -> dict:
    x = [feats.get(k) if feats.get(k) is not None else card["impute_means"][k]
         for k in card["features"]]
    xs = [(x[j] - card["std_mu"][j]) / card["std_sd"][j] for j in range(len(x))]
    contrib = [card["weights"][j] * xs[j] for j in range(len(xs))]
    p = sigmoid(card["bias"] + sum(contrib))
    drivers = sorted(
        ({"feature": card["features"][j], "value": round(x[j], 2),
          "contribution": round(contrib[j], 3)} for j in range(len(x))),
        key=lambda t: abs(t["contribution"]), reverse=True)
    return {"risk_score": round(p, 4), "drivers": drivers}


def leave_one_out(rows: list[dict]) -> list[dict]:
    """Honest test: retrain excluding each failure, then score it vs everyone."""
    out = []
    for pc, pname in POSITIVE_CERTS.items():
        if not any(r["cert"] == pc for r in rows):
            continue
        card, _ = train([r for r in rows if r["cert"] != pc])
        scored = [(r["cert"], score_vector(card, r["features"])["risk_score"]) for r in rows]
        scored.sort(key=lambda t: t[1], reverse=True)
        rank = next(i for i, (c, _) in enumerate(scored) if c == pc) + 1
        out.append({"cert": pc, "name": pname, "risk": next(s for c, s in scored if c == pc),
                    "rank": rank, "n": len(scored),
                    "percentile": round((1 - (rank - 1) / len(scored)) * 100, 1)})
    return out


def save_card(card: dict) -> None:
    MODEL_CARD.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CARD.write_text(json.dumps(card, indent=2), encoding="utf-8")


def load_card() -> dict | None:
    return json.loads(MODEL_CARD.read_text(encoding="utf-8")) if MODEL_CARD.exists() else None
