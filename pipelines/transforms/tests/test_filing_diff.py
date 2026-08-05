"""Feature 12 (filing diff) tests — synthetic quarters, no network.

A metric that is stable for several quarters then jumps should be flagged with a
high z; a metric that drifts smoothly should not.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.filing_diff import diff  # noqa: E402


def _q(label, **vals):
    base = {"quarter": label, "name": "TEST BANK"}
    base.update(vals)
    return base


def test_sudden_jump_is_flagged():
    # uninsured deposits stable ~100, then jumps to 130 in the newest quarter
    quarters = [
        _q("2026Q1", uninsured_deposits=130, total_deposits=200),
        _q("2025Q4", uninsured_deposits=101, total_deposits=200),
        _q("2025Q3", uninsured_deposits=100, total_deposits=200),
        _q("2025Q2", uninsured_deposits=99, total_deposits=200),
        _q("2025Q1", uninsured_deposits=100, total_deposits=200),
    ]
    res = diff(quarters)
    flagged = {f["metric"] for f in res["flags"]}
    assert "uninsured_deposits" in flagged
    top = next(f for f in res["flags"] if f["metric"] == "uninsured_deposits")
    assert top["direction"] == "up" and top["z"] is not None and top["z"] > 2


def test_smooth_drift_not_flagged():
    # steady ~1%/quarter growth — never an outlier vs its own history
    vals = [104, 103, 102, 101, 100]
    quarters = [_q(f"q{i}", total_assets=v) for i, v in enumerate(vals)]
    res = diff(quarters)
    assert all(f["metric"] != "total_assets" for f in res["flags"])


def test_default_compares_two_newest():
    quarters = [_q("2026Q1", total_assets=100), _q("2025Q4", total_assets=90),
                _q("2025Q3", total_assets=90)]
    res = diff(quarters)
    assert res["to_quarter"] == "2026Q1" and res["from_quarter"] == "2025Q4"


def test_line_items_cover_every_tracked_item_side_by_side():
    """The side-by-side view roadmap section 9 specifies needs BOTH quarters' raw
    values for every tracked line, not just the ones that cleared the z-score bar —
    that used to be all `flags` gave you, which is the flag list with extra steps,
    not a real side-by-side comparison."""
    from banklens_transforms.filing_diff import TRACKED
    quarters = [
        _q("2026Q1", uninsured_deposits=130, total_deposits=200),
        _q("2025Q4", uninsured_deposits=101, total_deposits=200),
        _q("2025Q3", uninsured_deposits=100, total_deposits=200),
    ]
    res = diff(quarters)
    assert len(res["line_items"]) == len(TRACKED)
    by_metric = {li["metric"]: li for li in res["line_items"]}
    # a flagged item: both raw values present, change/z/direction populated
    ud = by_metric["uninsured_deposits"]
    assert ud["quarter_a_value"] == 101 and ud["quarter_b_value"] == 130
    assert ud["flagged"] is True and ud["change"] is not None
    # an item with no data anywhere in these synthetic quarters: still listed, not
    # silently dropped, with an explicit "no verdict" shape rather than a crash
    cet1 = by_metric["cet1_ratio"]
    assert cet1["quarter_a_value"] is None and cet1["change"] is None
    assert cet1["flagged"] is False
    # flagged line_items must be exactly the flags list, just not filtered out
    assert {li["metric"] for li in res["line_items"] if li["flagged"]} == \
           {f["metric"] for f in res["flags"]}


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
