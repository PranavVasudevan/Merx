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
            "change": None, "z": None, "direction": None, "flagged": False, "note": note,
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
        mean = sum(hist) / len(hist) if hist else 0.0
        var = sum((c - mean) ** 2 for c in hist) / len(hist) if len(hist) > 1 else 0.0
        std = var ** 0.5
        z = (change - mean) / std if std > 0 else None

        material = abs(change) >= _FLOOR[kind]
        flagged = ((z is not None and abs(z) >= z_threshold and material)
                   or (z is None and abs(change) >= _BIG[kind]))

        entry.update({
            "change": round(change, 2), "z": round(z, 2) if z is not None else None,
            "direction": "up" if change > 0 else "down", "flagged": flagged,
        })
        line_items.append(entry)

        if flagged:
            flags.append({
                "item": label, "metric": key, "kind": kind,
                "change": round(change, 2),
                "unit": "%" if kind == "dollar" else "pp",
                "z": round(z, 2) if z is not None else None,
                "direction": "up" if change > 0 else "down",
                "note": note,
            })

    flags.sort(key=lambda f: abs(f["z"]) if f["z"] is not None else 0, reverse=True)
    return {
        "name": quarters_desc[0].get("name"),
        "from_quarter": labels[ia], "to_quarter": labels[ib], "span_quarters": span,
        "n_flags": len(flags), "flags": flags,
        # The side-by-side view roadmap section 9 specifies: EVERY tracked line item
        # with both quarters' raw values, not just the ones that cleared the z-score
        # bar — a "side-by-side" comparison that only shows outliers isn't side-by-side,
        # it's just the flag list with extra steps.
        "line_items": line_items,
    }
