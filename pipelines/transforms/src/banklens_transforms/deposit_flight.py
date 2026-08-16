"""Feature 13 — Deposit-Flight Early-Warning (the showcase).

Classifies banks by structural resemblance to real bank-run cases. Trained on a
POOLED cross-section spanning two real financial crises 15 years apart — 2022Q4
(the quarter before the March-2023 failures: SVB, Signature, First Republic — the
ONLY significant 2023 failures) and 2008Q1 (the quarter before 2008's ~25 bank
failures, IndyMac's July-2008 collapse the best-known among them) — labeling
every bank that actually failed within the landed population as a positive
(`derive_positive_certs`, landed from FDIC's own `failures` endpoint — real data,
not a hand-picked handful), then validated against history: "trained WITHOUT this
bank, would it still have flagged it?" (leave-one-out), across BOTH crises.

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
uninsured-institutional-deposit-flight structural pattern SVB/Signature/First
Republic share and the feature set is tuned to catch. Its most anomalous feature is instead
its deposit_growth_1yr (~+63% in the year before failure — rapid, hot-money-style
funding growth). Whether the model flags it well or poorly is an honest empirical
question, not something to assume either way — see the CLI's leave-one-out output.

Washington Mutual (also a real, famous 2008 depositor run — a ~$16.7B outflow in the
10 days before failure) is deliberately EXCLUDED, not forgotten: at ~$307B in assets
it exceeds every other training example by 10-60x even now that the landed
population spans the full FDIC universe (B3), and pooling it in risks the model
learning size-correlated confounds that don't generalize back down to the
population it will actually score. `derive_positive_certs` finds it (it's a real
2008 failure, present in the widened 2008Q1 population) and `EXCLUDED_CANDIDATES`
removes it explicitly, with this reason — a data-driven filter, not a silent
absence. A production build would either special-case a separate large-bank
cohort/model, or a size-conditional feature set.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from .data_quality import exclusion_for
from .gold import gold_features
from .logreg import LogisticRegression, auc, sigmoid
from .silver import to_bank_financials

FEATURES = ["uninsured_deposit_pct", "htm_to_equity", "securities_to_assets",
            "loan_to_deposit_pct", "deposit_growth_1yr"]

# Real deposit-run failures, pooled across two crises: 2023 (trained on 2022Q4) +
# 2008 (trained on 2008Q1). Docs/audit/04-remediation-prompts.md B6: this dict USED
# to be hand-typed; it is now `derive_positive_certs`'s output, landed FDIC data
# (sources/fdic.py's `failures` endpoint) rather than a fixed 4-bank list — so a
# future crisis's failures are picked up automatically the next time the model is
# retrained, not only after someone remembers to edit this file. Kept as a plain
# dict (not recomputed on import) so `_matrix`/`leave_one_out`/every existing caller
# is unchanged; `deposit_flight_cli.py` calls `derive_positive_certs` and reassigns
# this at train time.
POSITIVE_CERTS = {24735: "Silicon Valley Bank", 57053: "Signature Bank",
                  59017: "First Republic Bank", 29730: "IndyMac Bank"}

# Documented, not silently dropped — see the module docstring for why each is excluded.
# Applied by `derive_positive_certs` AFTER the data-driven derivation, so a candidate
# has to be found by real data first, then explicitly excluded with a stated reason —
# not just absent because the query happened not to surface it.
EXCLUDED_CANDIDATES = {
    32633: {"name": "Washington Mutual Bank", "reason":
            "assets ~$307B at failure (2008) — exceeds every other training "
            "example by 10-60x even in the widened full-universe population (B3); "
            "pooling it in would risk the model learning size confounds rather "
            "than structural risk signal."},
}

MODEL_CARD = Path(__file__).resolve().parents[4] / "ml" / "deposit_flight" / "model_card.json"
# G8 — content-addressed, immutable card history. A retrain used to overwrite
# MODEL_CARD in place, so nothing recorded which card actually produced a
# previously shown score, and a retrain silently replaced it out from under
# every user looking at a number computed from the old one. `CARDS_DIR` keeps
# every card ever trained, named by its own content hash; `CURRENT_POINTER` is
# a plain text file holding the hash of the live card (Windows has no cheap
# unprivileged symlink, so a pointer file — same idea, portable).
CARDS_DIR = MODEL_CARD.parent / "cards"
CURRENT_POINTER = CARDS_DIR / "current"


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


def derive_positive_certs(failures: list[dict], population_certs: set[int],
                          fail_years: set[str]) -> dict[int, str]:
    """Real positives for one training era: FDIC failures (`sources/fdic.py`'s
    `failures` endpoint, landed by `deposit_flight_cli.py`) whose CERT was
    actually IN that era's own landed training-quarter population, and whose
    `FAILYR` falls in `fail_years` — e.g. `{"2023"}` for the 2022Q4 cohort,
    `{"2008"}` for the 2008Q1 cohort. `EXCLUDED_CANDIDATES` is applied by the
    caller, not here, so this function's raw output stays independently
    auditable (a candidate must be found by real data before it can be
    excluded with a stated reason, not simply absent from this dict).

    This replaces a hand-typed 4-bank dict with a real query, but keeps the
    same causal shape: "a bank landed at time T that failed shortly after is a
    positive for a model trained at T" — not every FDIC failure ever, which
    would pool in banks the model was never in a position to have scored.

    Only `RESTYPE == "FAILURE"` rows count. The FDIC `failures` endpoint also
    carries "ASSISTANCE" rows — banks that received FDIC open-bank assistance
    but did NOT close (found live: CERT 7213, Citibank, N.A. — very much a
    surviving bank — has a 2008 "ASSISTANCE" row from the crisis-era Citigroup/
    Wachovia federal-assistance episode; treating that as a "failure" would
    have put a bank that never failed into the positive set). 3,522 of 4,115
    landed rows are real failures; 593 are assistance-only (verified live).
    """
    out: dict[int, str] = {}
    for f in failures:
        cert = f.get("CERT")
        if (f.get("RESTYPE") == "FAILURE" and cert in population_certs
                and f.get("FAILYR") in fail_years):
            # `or` fallback: a landed failures row missing NAME shouldn't turn
            # into a fabricated None entry in a dict this function promises is
            # str-valued -- same disclosed-fallback pattern tools.py already
            # uses for a missing bank name elsewhere.
            out[cert] = f.get("NAME") or f"CERT {cert}"
    return out


def build_rows(records: list[dict], prior_dep_usd: dict[int, float]
               ) -> tuple[list[dict], list[dict]]:
    """Training rows for the deposit-flight model, plus the exclusions applied.

    Returns (rows, exclusions). Non-deposit-funded charters are dropped here rather
    than clipped later — see banklens_transforms.data_quality for why, and for the
    measured damage they did to the previous model card (imputation mean 7,846.88%).
    The exclusions are returned, not swallowed, so the CLI and the UI can name them.
    """
    rows, exclusions = [], []
    for r in records:
        s = to_bank_financials(r)
        exc = exclusion_for(s)
        if exc is not None:
            exclusions.append(exc)
            continue
        g = gold_features(s)
        cert = s.get("cert_number")
        # s.get("cert_number") is Any | None (an untyped Silver dict row);
        # dict.get on the wrong-type/None key is safe at runtime (returns the
        # None default), same as a genuinely-missing prior-quarter deposit.
        rows.append({"cert": cert, "name": s.get("name"),
                     "features": features_from(s, g, prior_dep_usd.get(cert))})  # type: ignore[arg-type]
    return rows, exclusions


def _impute_means(rows: list[dict]) -> dict:
    means = {}
    for k in FEATURES:
        vals = [r["features"][k] for r in rows if r["features"].get(k) is not None]
        means[k] = sum(vals) / len(vals) if vals else 0.0
    return means


def _matrix(rows, means, positive_certs):
    X, y, certs, names = [], [], [], []
    for r in rows:
        X.append([r["features"][k] if r["features"].get(k) is not None else means[k]
                  for k in FEATURES])
        y.append(1 if r["cert"] in positive_certs else 0)
        certs.append(r["cert"]); names.append(r["name"])
    return X, y, certs, names


def _standardize(X):
    n, d = len(X), len(X[0])
    cols = list(zip(*X, strict=True))
    mu = [sum(c) / n for c in cols]
    sd = [(sum((v - mu[j]) ** 2 for v in cols[j]) / n) ** 0.5 or 1.0 for j in range(d)]
    Xs = [[(X[i][j] - mu[j]) / sd[j] for j in range(d)] for i in range(n)]
    return Xs, mu, sd


def _standardize_per_era(X: list[list[float]], eras: list[str]
                          ) -> tuple[list[list[float]], dict[str, tuple[list[float], list[float]]]]:
    """C2 — standardize each era's rows against ITS OWN mean/sd before pooling.
    The two crises this model pools (2008, 2023) had different rate/macro
    environments; even though every feature here is a ratio (not a dollar
    level), a bank's z-score under global pooled standardization is still
    shifted by whichever era's distribution happens to dominate. Standardizing
    within era asks "how unusual was this bank FOR ITS OWN ERA" instead."""
    groups: dict[str, list[int]] = {}
    for i, e in enumerate(eras):
        groups.setdefault(e, []).append(i)
    Xs: list[list[float] | None] = [None] * len(X)
    stats: dict[str, tuple[list[float], list[float]]] = {}
    for era, idxs in groups.items():
        sub_s, mu, sd = _standardize([X[i] for i in idxs])
        stats[era] = (mu, sd)
        for k, i in enumerate(idxs):
            Xs[i] = sub_s[k]
    return Xs, stats  # type: ignore[return-value]


def _kfold_indices(n: int, k: int, seed: int) -> list[tuple[list[int], list[int]]]:
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    folds = [idx[i::k] for i in range(k)]
    return [(sum((f for j, f in enumerate(folds) if j != i), []), folds[i]) for i in range(k)]


def cv_select_l2(rows: list[dict], positive_certs: dict[int, str], *,
                  candidates: tuple[float, ...] = (0.1, 0.3, 1.0, 3.0, 10.0),
                  k: int = 4, epochs: int = 500, seed: int = 7) -> dict:
    """C2 — small k-fold CV sweep over the L2 penalty, pure Python (no new
    dependency — same constraint logreg.py documents). `epochs=500` for the
    same reason bootstrap_stats reduces it: comparing candidates by relative
    CV AUC doesn't need each fold's fit to fully converge, and a naive
    5-candidate x k-fold x 2000-epoch sweep at the real ~9,000-row population
    would take tens of minutes. The FINAL model is refit at train()'s full
    2000-epoch default using whichever l2 this selects.
    """
    means = _impute_means(rows)
    X, y, _, _ = _matrix(rows, means, positive_certs)
    n = len(X)
    folds = _kfold_indices(n, k, seed)
    results = []
    for l2 in candidates:
        fold_aucs = []
        for train_idx, test_idx in folds:
            y_tr = [y[i] for i in train_idx]
            y_te = [y[i] for i in test_idx]
            if sum(y_tr) == 0 or sum(y_te) == 0 or sum(y_te) == len(y_te):
                continue  # a fold with no positives on either side can't score an AUC
            Xs_tr, mu, sd = _standardize([X[i] for i in train_idx])
            Xs_te = [[(X[i][j] - mu[j]) / sd[j] for j in range(len(mu))] for i in test_idx]
            model = LogisticRegression(lr=0.2, epochs=epochs, l2=l2).fit(Xs_tr, y_tr)
            fold_aucs.append(auc(y_te, model.predict_proba(Xs_te)))
        mean_auc = sum(fold_aucs) / len(fold_aucs) if fold_aucs else None
        results.append({"l2": l2, "mean_cv_auc": round(mean_auc, 4) if mean_auc is not None else None,
                         "folds_used": len(fold_aucs)})
    usable = [r for r in results if r["mean_cv_auc"] is not None]
    # `usable` is already filtered to real (non-None) mean_cv_auc values, but
    # `results`/`r` are untyped dicts, so mypy can't narrow a dict VALUE from
    # a filter predicate the way it narrows a plain variable.
    best = max(usable, key=lambda r: r["mean_cv_auc"]) if usable else None  # type: ignore[arg-type,return-value]
    return {"candidates": results, "selected_l2": best["l2"] if best else 1.0, "k": k, "epochs": epochs}


def era_standardization_report(rows: list[dict], positive_certs: dict[int, str], *,
                                l2: float = 1.0, k: int = 4, epochs: int = 500,
                                seed: int = 11, margin: float = 0.01) -> dict:
    """C2 — CV-compare pooled global standardization against per-era
    standardization, and report which one CV AUC actually prefers, rather than
    assuming pooling is fine (or that era-splitting must help) either way. A
    negative result — pooling ties or wins — is reported as such: these are
    ratio features, which is exactly the property that was supposed to make
    them era-comparable in the first place (see the module docstring), so
    finding that the era split doesn't matter would be a real, useful measured
    confirmation of that design choice, not a failure to find something.
    `margin` is the minimum CV AUC improvement required to prefer per-era
    (avoids flipping the decision on noise).
    """
    if not all(r.get("era") for r in rows):
        return {"comparable": False, "reason": "rows missing era tags"}
    means = _impute_means(rows)
    X, y, _, _ = _matrix(rows, means, positive_certs)
    eras = [r["era"] for r in rows]
    n = len(X)
    folds = _kfold_indices(n, k, seed)

    def _cv_auc(per_era: bool) -> float | None:
        fold_aucs = []
        for train_idx, test_idx in folds:
            y_tr = [y[i] for i in train_idx]
            y_te = [y[i] for i in test_idx]
            if sum(y_tr) == 0 or sum(y_te) == 0 or sum(y_te) == len(y_te):
                continue
            X_tr = [X[i] for i in train_idx]
            if per_era:
                Xs_tr, stats = _standardize_per_era(X_tr, [eras[i] for i in train_idx])
                fallback = next(iter(stats.values()))
                Xs_te = []
                for i in test_idx:
                    mu, sd = stats.get(eras[i], fallback)
                    Xs_te.append([(X[i][j] - mu[j]) / sd[j] for j in range(len(mu))])
            else:
                Xs_tr, mu, sd = _standardize(X_tr)
                Xs_te = [[(X[i][j] - mu[j]) / sd[j] for j in range(len(mu))] for i in test_idx]
            model = LogisticRegression(lr=0.2, epochs=epochs, l2=l2).fit(Xs_tr, y_tr)
            fold_aucs.append(auc(y_te, model.predict_proba(Xs_te)))
        return round(sum(fold_aucs) / len(fold_aucs), 4) if fold_aucs else None

    pooled_auc = _cv_auc(per_era=False)
    era_auc = _cv_auc(per_era=True)
    prefer_era = era_auc is not None and (pooled_auc is None or era_auc > pooled_auc + margin)
    decision = "per_era" if prefer_era else "pooled"
    return {
        "comparable": True, "k": k, "epochs": epochs, "margin": margin,
        "pooled_cv_auc": pooled_auc, "per_era_cv_auc": era_auc,
        "decision": decision,
        "note": (f"per-era standardization improved CV AUC by more than {margin} — adopted for training."
                  if decision == "per_era" else
                  "pooling performed as well or better under CV (within the margin) — kept pooled "
                  "standardization; the two-era rate/macro confound this was meant to catch was not "
                  "measurably costing the model anything on this feature set, which is entirely ratios "
                  "rather than dollar levels — a real, measured result, not an assumption."),
    }


def train(rows: list[dict], *, trained_on: str = "2022Q4",
         positive_certs: dict[int, str] | None = None, l2: float = 1.0,
         use_era_standardization: bool = False,
         scoring_era: str | None = None) -> tuple[dict, dict]:
    """`positive_certs` defaults to the module-level `POSITIVE_CERTS` (kept for
    any existing caller that trained against the old hardcoded 4-bank dict);
    `deposit_flight_cli.py` passes the real, landed-data-derived set explicitly
    (see `derive_positive_certs`) rather than mutating the module global, so a
    caller can never be surprised by which positives a given `train()` call
    actually used.

    `l2` (C2) is chosen by `cv_select_l2` rather than hardcoded. When
    `use_era_standardization` (C2, decided by `era_standardization_report`) is
    set, `rows` must carry an `era` key per row and `std_mu`/`std_sd` in the
    returned card become PER-ERA dicts rather than flat lists; `scoring_era`
    names which era's stats a live (current-quarter, era-unknown) bank should
    be scored against — `score_vector` falls back to `card["scoring_era"]`
    when its own `era` argument is omitted, and to plain flat lists when
    `use_era_standardization` was never enabled at all.
    """
    positive_certs = POSITIVE_CERTS if positive_certs is None else positive_certs
    means = _impute_means(rows)
    X, y, certs, names = _matrix(rows, means, positive_certs)
    scoring_era_resolved = None
    if use_era_standardization:
        eras = [r.get("era", "unknown") for r in rows]
        Xs, era_stats = _standardize_per_era(X, eras)
        std_mu = {e: mu for e, (mu, sd) in era_stats.items()}
        std_sd = {e: sd for e, (mu, sd) in era_stats.items()}
        scoring_era_resolved = scoring_era or max(era_stats)
    else:
        Xs, std_mu, std_sd = _standardize(X)
    model = LogisticRegression(lr=0.2, epochs=2000, l2=l2).fit(Xs, y)
    scores = model.predict_proba(Xs)
    card = {"features": FEATURES, "impute_means": means, "std_mu": std_mu, "std_sd": std_sd,
            "weights": model.w, "bias": model.b, "trained_on": trained_on,
            "positives": sorted(positive_certs), "auc": auc(y, scores), "l2": l2}
    if scoring_era_resolved:
        card["scoring_era"] = scoring_era_resolved
    return card, {"y": y, "certs": certs, "names": names, "scores": scores}


def imputation_rates(rows: list[dict]) -> dict[str, float]:
    """Share of training rows (%) where each feature was missing and stood in
    for by `_impute_means` — C1: the model card must disclose this, since a
    heavily-imputed feature is contributing noise dressed as signal."""
    n = len(rows)
    if n == 0:
        return {k: 0.0 for k in FEATURES}
    return {k: round(sum(1 for r in rows if r["features"].get(k) is None) / n * 100, 2)
            for k in FEATURES}


def bootstrap_stats(rows: list[dict], positive_certs: dict[int, str], *,
                     n_boot: int = 40, epochs: int = 500, l2: float = 1.0,
                     seed: int = 42) -> dict:
    """Bootstrap sampling distribution for every coefficient and for AUC —
    percentile confidence intervals, not analytic SE-based ones (which the tiny
    positive count, a handful of real failures, would make unreliable anyway).

    Each round resamples rows WITH replacement, refits on the resample (using
    the resample's own imputation means/standardization, since that is what a
    retrain would actually see), then evaluates the refit model's AUC against
    the full ORIGINAL sample. A resample that happens to draw zero positives or
    zero negatives can't fit/evaluate a meaningful AUC and is skipped — `n_boot`
    vs `n_boot_used` in the result discloses how often that happened.

    `epochs` is deliberately far below train()'s 2000-epoch default: at the
    real population size (~9,000 pooled rows) a single 2000-epoch fit measured
    ~25s in pure Python, which would put a naive 200-resample bootstrap at over
    an hour. A bootstrap CI only needs each resample's fit to land in the same
    neighborhood the full run converges to, not full convergence itself — 500
    epochs with L2=1.0 gets there in ~6s. `n_boot=40` is a further explicit
    compute/precision tradeoff (documented, not hidden) that keeps a full
    retrain+bootstrap CLI run under ~5 minutes.

    This is deliberately still "in-sample" in spirit (the eval set overlaps the
    fit set) — the point of C1 is not to invent a held-out test this dataset is
    too small to support, but to show the SPREAD a resampled refit produces,
    which the single point-estimate AUC/coefficients hid entirely.
    """
    rng = random.Random(seed)
    n = len(rows)
    full_means = _impute_means(rows)
    X_full, y_full, _, _ = _matrix(rows, full_means, positive_certs)

    boot_coefs: dict[str, list[float]] = {k: [] for k in FEATURES}
    boot_bias: list[float] = []
    boot_aucs: list[float] = []
    for _ in range(n_boot):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        y_sample = [1 if r["cert"] in positive_certs else 0 for r in sample]
        if sum(y_sample) == 0 or sum(y_sample) == len(y_sample):
            continue
        sample_means = _impute_means(sample)
        X_s, y_s, _, _ = _matrix(sample, sample_means, positive_certs)
        Xs_s, mu_s, sd_s = _standardize(X_s)
        model = LogisticRegression(lr=0.2, epochs=epochs, l2=l2).fit(Xs_s, y_s)
        for j, k in enumerate(FEATURES):
            boot_coefs[k].append(model.w[j])
        boot_bias.append(model.b)
        Xs_eval = [[(X_full[i][j] - mu_s[j]) / sd_s[j] for j in range(len(FEATURES))]
                   for i in range(len(X_full))]
        boot_aucs.append(auc(y_full, model.predict_proba(Xs_eval)))

    def _ci(vals: list[float]) -> dict:
        if not vals:
            return {"lo": None, "median": None, "hi": None}
        s = sorted(vals)
        m = len(s)
        return {"lo": round(s[max(0, int(0.025 * m))], 4),
                "median": round(s[m // 2], 4),
                "hi": round(s[min(m - 1, int(0.975 * m))], 4)}

    return {
        "n_boot": n_boot,
        "n_boot_used": len(boot_aucs),
        "coefficients": {k: _ci(v) for k, v in boot_coefs.items()},
        "bias": _ci(boot_bias),
        "auc": _ci(boot_aucs),
    }


def pr_curve(y: list[int], scores: list[float], n_points: int = 50) -> list[dict]:
    """Precision-recall at the TRUE base rate (a handful of positives among
    ~1,600+ rows) — not resampled or balanced, because the whole point is to
    show how the model performs at the real rarity of failure, where accuracy
    and even AUC can look deceptively good while precision at any usable
    recall is poor."""
    thresholds = sorted({round(s, 4) for s in scores}, reverse=True)
    if len(thresholds) > n_points:
        step = len(thresholds) / n_points
        thresholds = [thresholds[int(i * step)] for i in range(n_points)]
    out = []
    for t in thresholds:
        tp = sum(1 for s, yy in zip(scores, y, strict=True) if s >= t and yy == 1)
        fp = sum(1 for s, yy in zip(scores, y, strict=True) if s >= t and yy == 0)
        fn = sum(1 for s, yy in zip(scores, y, strict=True) if s < t and yy == 1)
        out.append({
            "threshold": t,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "tp": tp, "fp": fp,
        })
    return out


def roc_curve(y: list[int], scores: list[float], n_points: int = 50) -> list[dict]:
    """ROC points (false-positive rate vs. true-positive rate) swept over the
    same score thresholds `pr_curve` uses, plus the endpoints (0,0) and (1,1)
    so the plotted curve always reaches both corners. `auc` (logreg.py) already
    reports the scalar rank-based area under this curve; this persists the
    actual curve so a statistician can see WHERE the tradeoff sits (e.g. a
    curve that only clears the diagonal at very high FPR is a very different
    finding from one that clears it early), not just the summary number."""
    n_pos = sum(1 for yy in y if yy == 1)
    n_neg = sum(1 for yy in y if yy == 0)
    if n_pos == 0 or n_neg == 0:
        return []
    thresholds = sorted({round(s, 4) for s in scores}, reverse=True)
    if len(thresholds) > n_points:
        step = len(thresholds) / n_points
        thresholds = [thresholds[int(i * step)] for i in range(n_points)]
    out = [{"threshold": None, "fpr": 0.0, "tpr": 0.0, "tp": 0, "fp": 0}]
    for t in thresholds:
        tp = sum(1 for s, yy in zip(scores, y, strict=True) if s >= t and yy == 1)
        fp = sum(1 for s, yy in zip(scores, y, strict=True) if s >= t and yy == 0)
        out.append({
            "threshold": t,
            "fpr": round(fp / n_neg, 4),
            "tpr": round(tp / n_pos, 4),
            "tp": tp, "fp": fp,
        })
    out.append({"threshold": None, "fpr": 1.0, "tpr": 1.0, "tp": n_pos, "fp": n_neg})
    return out


def calibration_curve(y: list[int], scores: list[float], n_bins: int = 10) -> list[dict]:
    """Bin predicted probabilities and compare to the observed positive rate in
    each bin — a well-calibrated model's points sit near the diagonal. With
    only a handful of true positives most bins will show 0% observed, which is
    itself the honest finding this feature exists to surface, not a bug to
    smooth away."""
    pairs = sorted(zip(scores, y, strict=True), key=lambda t: t[0])
    n = len(pairs)
    if n == 0:
        return []
    bin_size = max(1, n // n_bins)
    out = []
    for i in range(0, n, bin_size):
        chunk = pairs[i:i + bin_size]
        if not chunk:
            continue
        out.append({
            "mean_predicted": round(sum(s for s, _ in chunk) / len(chunk), 4),
            "observed_rate": round(sum(yy for _, yy in chunk) / len(chunk), 4),
            "n": len(chunk),
        })
    return out


def population_percentile(target_score: float, all_scores: list[float]) -> dict:
    """Where a score ranks among every bank scored this quarter — the
    resemblance percentile/decile the UI shows INSTEAD OF the raw sigmoid
    output. `risk_score` is not a calibrated probability of failure (C1's
    calibration curve shows why), so presenting it directly as "62.4%" visually
    asserts a probability the model does not produce; a percentile only claims
    what is actually true — relative structural resemblance within this
    quarter's population."""
    if not all_scores:
        return {"resemblance_percentile": None, "resemblance_decile": None}
    n = len(all_scores)
    below = sum(1 for s in all_scores if s < target_score)
    pct = round(below / n * 100, 1)
    decile = min(10, int(pct // 10) + 1)
    return {"resemblance_percentile": pct, "resemblance_decile": decile}


def score_vector(card: dict, feats: dict, era: str | None = None) -> dict:
    """`era` (C2) only matters when the card was trained with
    `use_era_standardization=True`, in which case `std_mu`/`std_sd` are dicts
    keyed by era rather than flat lists — pass the row's own era when scoring
    a KNOWN-era training row (leave_one_out), and omit it when scoring a live,
    era-unknown current-quarter bank, which falls back to `card["scoring_era"]`
    (set at train time to the most contemporary pooled era)."""
    # The else-branch always supplies a real impute mean when feats.get(k) is
    # None, so x[j] is never actually None -- but `feats`/`card` are untyped
    # dicts, and mypy doesn't narrow a repeated feats.get(k) call across the
    # condition and the true-branch the way it would a bound variable.
    x = [feats.get(k) if feats.get(k) is not None else card["impute_means"][k]
         for k in card["features"]]
    if isinstance(card["std_mu"], dict):
        use_era = era or card.get("scoring_era") or next(iter(card["std_mu"]))
        mu, sd = card["std_mu"][use_era], card["std_sd"][use_era]
    else:
        mu, sd = card["std_mu"], card["std_sd"]
    xs = [(x[j] - mu[j]) / sd[j] for j in range(len(x))]
    contrib = [card["weights"][j] * xs[j] for j in range(len(xs))]
    p = sigmoid(card["bias"] + sum(contrib))
    drivers = sorted(
        ({"feature": card["features"][j], "value": round(x[j], 2),  # type: ignore[arg-type]
          "contribution": round(contrib[j], 3)} for j in range(len(x))),
        key=lambda t: abs(t["contribution"]), reverse=True)
    return {"risk_score": round(p, 4), "drivers": drivers}


def leave_one_out(rows: list[dict], positive_certs: dict[int, str] | None = None, *,
                   l2: float = 1.0, use_era_standardization: bool = False,
                   scoring_era: str | None = None) -> list[dict]:
    """Honest test: retrain excluding each failure, then score it vs everyone.
    `l2`/`use_era_standardization`/`scoring_era` (C2) should match whatever
    the real card was trained with, so LOO evaluates the SAME modeling choices
    the persisted model actually uses, not train()'s bare defaults."""
    positive_certs = POSITIVE_CERTS if positive_certs is None else positive_certs
    out = []
    for pc, pname in positive_certs.items():
        if not any(r["cert"] == pc for r in rows):
            continue
        card, _ = train([r for r in rows if r["cert"] != pc], positive_certs=positive_certs,
                         l2=l2, use_era_standardization=use_era_standardization,
                         scoring_era=scoring_era)
        scored = [(r["cert"], score_vector(card, r["features"], era=r.get("era"))["risk_score"])
                  for r in rows]
        scored.sort(key=lambda t: t[1], reverse=True)
        rank = next(i for i, (c, _) in enumerate(scored) if c == pc) + 1
        out.append({"cert": pc, "name": pname, "risk": next(s for c, s in scored if c == pc),
                    "rank": rank, "n": len(scored),
                    "percentile": round((1 - (rank - 1) / len(scored)) * 100, 1)})
    return out


def _stable_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def card_hash(card: dict) -> str:
    """Content hash of a model card — same stable-JSON + sha256 convention as
    Bronze partition provenance checksums (banklens_ingestion.provenance.
    sha256_of), truncated to 16 hex chars for a filename-friendly id (per-card
    collision odds at this population size are astronomically low; a full
    256-bit hash buys nothing a filename needs). Computed over the card MINUS
    its own `card_hash` field, so re-hashing a loaded card reproduces the same
    value instead of hashing itself — and an identical retrain (same data,
    same code) content-addresses to the same file rather than a spurious new
    version."""
    raw = {k: v for k, v in card.items() if k != "card_hash"}
    return hashlib.sha256(_stable_json(raw).encode("utf-8")).hexdigest()[:16]


def save_card(card: dict) -> str:
    """G8 — write an immutable, content-addressed card and advance `current`
    to point at it; every prior card stays on disk under `CARDS_DIR`, so a
    score computed against an older card can always be reproduced exactly by
    loading it back via its hash, however many retrains happen afterward.
    Returns the hash so callers (the CLI, tests) can log/verify it.
    """
    h = card_hash(card)
    versioned = {**card, "card_hash": h}
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    card_path = CARDS_DIR / f"{h}.json"
    if not card_path.exists():  # immutable: never rewrite a hash already on disk
        card_path.write_text(json.dumps(versioned, indent=2), encoding="utf-8")
    CURRENT_POINTER.write_text(h, encoding="utf-8")
    # MODEL_CARD keeps mirroring `current` as a plain-path convenience for any
    # tooling that still reads it directly (docs, ad-hoc scripts) — the
    # versioned copy under CARDS_DIR is the actual system of record.
    MODEL_CARD.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CARD.write_text(json.dumps(versioned, indent=2), encoding="utf-8")
    return h


def load_card(card_hash_value: str | None = None) -> dict | None:
    """Loads the live (`current`) card by default. Pass a specific hash — as
    returned by `save_card`, or a card's own `card_hash` field — to load a
    RETAINED historical card instead, e.g. to reproduce a score exactly as it
    was shown before a later retrain moved `current`."""
    if card_hash_value:
        path = CARDS_DIR / f"{card_hash_value}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if CURRENT_POINTER.exists():
        path = CARDS_DIR / f"{CURRENT_POINTER.read_text(encoding='utf-8').strip()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    # Pre-G8 fallback: an environment that has model_card.json but no cards/
    # history yet (never retrained since this landed) still gets a live card.
    return json.loads(MODEL_CARD.read_text(encoding="utf-8")) if MODEL_CARD.exists() else None


def list_card_versions() -> list[dict]:
    """Every retained card, newest first — hash, trained-on label, AUC and a
    save timestamp — for a /model historical-version selector. Cards are
    immutable once written, so filesystem mtime doubles as the save time
    without needing to persist one separately."""
    if not CARDS_DIR.exists():
        return []
    out = []
    for p in CARDS_DIR.glob("*.json"):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "card_hash": c.get("card_hash", p.stem),
            "trained_on": c.get("trained_on"),
            "auc": c.get("auc"),
            "saved_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    out.sort(key=lambda r: r["saved_at"], reverse=True)
    return out
