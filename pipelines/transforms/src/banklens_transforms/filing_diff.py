"""Feature 12 — Filing Diff Tool (statistical change detection).

Auto-diffs a bank's filings between two quarters and flags **material** shifts —
but "material" is judged against *that bank's own* history, not an absolute cutoff.
A line item is flagged when its quarter-over-quarter move is a statistical outlier
(high |z|) versus the bank's typical move for that item, and the move clears a small
materiality floor (so a big z on a trivial wiggle is ignored).

Output: a structured "what changed and why it matters" summary between two quarters.

With only a few quarters of history the z-scores are rough (small-sample std); Phase 2
pulls deeper history for tighter baselines.
"""

from __future__ import annotations

import math

from banklens_transforms.gold import gold_features

# (key, kind, label, why-it-matters). kind: "dollar" -> % change; "ratio" -> pp change.
TRACKED = [
    ("total_assets", "dollar", "Total assets", "overall balance-sheet growth or shrinkage"),
    ("total_deposits", "dollar", "Total deposits", "the funding base — outflows are the run signal"),
    ("uninsured_deposits", "dollar", "Uninsured deposits", "run-prone funding; jumps raise flight risk"),
    ("total_loans_gross", "dollar", "Gross loans", "lending expansion or contraction"),
    ("cre_loans", "dollar", "CRE loans", "commercial-real-estate concentration shift"),
    ("c_and_i_loans", "dollar", "C&I loans", "commercial lending shift"),
    ("securities_afs", "dollar", "AFS securities", "mark-to-market-exposed securities book"),
    ("securities_htm", "dollar", "HTM securities", "hidden-loss-exposed book (the SVB angle)"),
    ("tier1_capital", "dollar", "Tier 1 capital", "the loss-absorbing capital base"),
    ("uninsured_deposit_pct", "ratio", "Uninsured deposit %", "structural funding-flight risk"),
    ("loan_to_deposit_pct", "ratio", "Loan-to-deposit %", "liquidity / funding intensity"),
    ("cet1_ratio", "ratio", "CET1 ratio", "capital adequacy"),
    ("concentration_ratio_cre", "ratio", "CRE concentration %", "sector concentration in the loan book"),
]

# materiality floors so a high z on a trivial move is ignored
_FLOOR = {"dollar": 2.0, "ratio": 0.3}       # % change / percentage-point change
_BIG = {"dollar": 8.0, "ratio": 1.0}         # used when there's no volatility baseline

# C12 — below this many historical same-span observations, a z-score computed
# from that tiny a sample standard deviation is closer to noise than signal
# (the extreme case: 2 observations gives a std computed from ONE degree of
# freedom, so any 3rd observation more than a hair off either of them reads as
# a huge z). Report None with a stated reason instead of a number that LOOKS
# precise but isn't.
MIN_OBSERVATIONS = 4

# C12 — the materiality floor also scales with THIS bank's own typical
# |change| for the item (mean absolute historical move), not just the flat
# absolute floor above: a bank whose CRE concentration naturally moves 3pp a
# quarter shouldn't have every ordinary quarter flagged just because 3pp
# clears the flat 0.3pp floor. `max()` with the flat floor keeps a genuinely
# quiet bank's small floor from shrinking to near-zero.
_FLOOR_SCALE = 0.5


def build_quarters(silver_rows_desc: list[dict]) -> list[dict]:
    """Merge each quarter's Silver row with its derived Gold ratios (newest-first)."""
    out = []
    for s in silver_rows_desc:
        m = dict(s)
        m.update(gold_features(s))
        out.append(m)
    return out


def _change(kind: str, old, new):
    if old is None or new is None:
        return None
    if kind == "dollar":
        return None if old == 0 else (new - old) / abs(old) * 100.0
    return new - old


def diff(quarters_desc: list[dict], quarter_a: str | None = None,
         quarter_b: str | None = None, *, z_threshold: float = 2.0) -> dict:
    """Diff quarter_a (older) -> quarter_b (newer). Defaults to the two most recent."""
    labels = [q.get("quarter") for q in quarters_desc]
    ib = 0 if quarter_b is None else labels.index(quarter_b)
    ia = 1 if quarter_a is None else labels.index(quarter_a)
    if ia < ib:                       # ensure a is older (higher index) than b
        ia, ib = ib, ia
    span = ia - ib or 1

    flags = []
    line_items = []
    for key, kind, label, note in TRACKED:
        val_a, val_b = quarters_desc[ia].get(key), quarters_desc[ib].get(key)
        change = _change(kind, val_a, val_b)

        entry = {
            "item": label, "metric": key, "kind": kind,
            "quarter_a_value": val_a, "quarter_b_value": val_b,
            "unit": "%" if kind == "dollar" else "pp",
            "change": None, "z": None, "n": 0, "z_reason": None,
            "direction": None, "flagged": False, "note": note,
        }
        if change is None:
            # Still listed — a "side-by-side" view must show a line item exists even
            # when one side is unreported, not silently omit the row.
            line_items.append(entry)
            continue

        # the bank's own distribution of same-span changes for this item,
        # EXCLUDING the transition being evaluated (don't let it damp its own z)
        hist = []
        for i in range(0, len(quarters_desc) - span):
            if i == ib:
                continue
            c = _change(kind, quarters_desc[i + span].get(key), quarters_desc[i].get(key))
            if c is not None:
                hist.append(c)
        n_obs = len(hist)
        mean = sum(hist) / n_obs if hist else 0.0
        var = sum((c - mean) ** 2 for c in hist) / n_obs if n_obs > 1 else 0.0
        std = var ** 0.5
        typical_magnitude = sum(abs(c) for c in hist) / n_obs if hist else 0.0

        # C12 — a z below MIN_OBSERVATIONS is reported as None with a stated
        # reason, not silently computed from a near-meaningless small sample.
        z, z_reason = None, None
        if n_obs < MIN_OBSERVATIONS:
            z_reason = (f"only {n_obs} historical observation(s) for this item "
                        f"(need >= {MIN_OBSERVATIONS}) — z not computed")
        elif std <= 0:
            z_reason = "zero historical variance for this item — z not computed"
        else:
            z = (change - mean) / std

        floor = max(_FLOOR[kind], _FLOOR_SCALE * typical_magnitude)
        material = abs(change) >= floor
        # No-reliable-z fallback: an absolute-move threshold, unchanged from
        # before C12 — still applies whenever z couldn't be computed (too few
        # observations OR zero historical variance), same as it always did.
        flagged = ((z is not None and abs(z) >= z_threshold and material)
                   or (z is None and abs(change) >= _BIG[kind]))

        entry.update({
            "change": round(change, 2), "z": round(z, 2) if z is not None else None,
            "n": n_obs, "z_reason": z_reason, "materiality_floor": round(floor, 3),
            "direction": "up" if change > 0 else "down", "flagged": flagged,
        })
        line_items.append(entry)

        if flagged:
            flags.append({
                "item": label, "metric": key, "kind": kind,
                "change": round(change, 2),
                "unit": "%" if kind == "dollar" else "pp",
                "z": round(z, 2) if z is not None else None,
                "n": n_obs,
                "direction": "up" if change > 0 else "down",
                "note": note,
            })

    flags.sort(key=lambda f: abs(f["z"]) if f["z"] is not None else 0, reverse=True)
    return {
        "cert": quarters_desc[0].get("cert_number"),
        "name": quarters_desc[0].get("name"),
        "from_quarter": labels[ia], "to_quarter": labels[ib], "span_quarters": span,
        "n_flags": len(flags), "flags": flags,
        # The side-by-side view roadmap section 9 specifies: EVERY tracked line item
        # with both quarters' raw values, not just the ones that cleared the z-score
        # bar — a "side-by-side" comparison that only shows outliers isn't side-by-side,
        # it's just the flag list with extra steps.
        "line_items": line_items,
    }


# ---- C13: multiple-testing control across the population ------------------

def _two_sided_p(z: float) -> float:
    """Two-sided normal-approximation p-value for a z-score, via erfc."""
    return math.erfc(abs(z) / math.sqrt(2))


def population_flag_summary(diffs: list[dict], *, z_threshold: float = 2.0,
                            fdr_alpha: float = 0.05) -> dict:
    """C13 — a raw `z >= z_threshold` rule applied independently to every
    (bank, tracked line item) pair produces false positives BY CHANCE ALONE:
    at the default 2.0 threshold, a two-sided normal test rejects ~4.55% of
    true nulls, so ~4.55% of every line item ever tested "flags" even if
    nothing unusual happened anywhere. `diffs`: one `diff()` result per bank
    for the SAME quarter transition (e.g. every landed bank's latest-vs-prior
    filing diff). Reports the expected false-positive count at the CURRENT
    threshold, and a Benjamini-Hochberg FDR-controlled alternative flag set
    computed from the same z-scores — the choice of which to trust is left to
    the caller/UI, not decided here.
    """
    tests = []
    for d in diffs:
        for item in d.get("line_items", []):
            if item.get("z") is not None:
                tests.append({
                    "cert": d.get("cert"), "name": d.get("name"),
                    "item": item["item"], "metric": item["metric"],
                    "change": item["change"], "unit": item["unit"], "z": item["z"],
                    "p": _two_sided_p(item["z"]), "flagged_raw": item["flagged"],
                })

    n_tests = len(tests)
    p_at_threshold = _two_sided_p(z_threshold)
    expected_false_positives = round(p_at_threshold * n_tests, 1)
    raw_flag_count = sum(1 for t in tests if t["flagged_raw"])

    # Benjamini-Hochberg: sort by p ascending, find the largest rank k where
    # p_(k) <= (k/m) * alpha, reject every test at or before that rank.
    ranked = sorted(tests, key=lambda t: t["p"])
    m = n_tests
    cutoff_rank = 0
    for k, t in enumerate(ranked, start=1):
        if t["p"] <= (k / m) * fdr_alpha:
            cutoff_rank = k
    fdr_flags = ranked[:cutoff_rank]
    fdr_flags.sort(key=lambda t: t["p"])

    return {
        "n_tests": n_tests,
        "z_threshold": z_threshold,
        "raw_flag_count": raw_flag_count,
        "expected_false_positives_at_threshold": expected_false_positives,
        "fdr_alpha": fdr_alpha,
        "fdr_flag_count": len(fdr_flags),
        "fdr_flags": fdr_flags,
        "note": (
            f"At the raw z>={z_threshold} threshold, ~{expected_false_positives} of the "
            f"{raw_flag_count} flags shown are expected by chance alone (normal-null "
            f"assumption, {n_tests} total tests). The FDR-controlled set below "
            f"({len(fdr_flags)} flags) bounds the expected false-discovery rate at "
            f"{fdr_alpha:.0%} instead — fewer flags, but each one is more likely real."
        ),
    }
