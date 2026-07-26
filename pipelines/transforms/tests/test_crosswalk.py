"""CERT<->CIK<->RSSD crosswalk tests, using the real name pairs discovered while
building this (Wells Fargo, Zions, Flagstar, and the Dime Community/Commercial
naming quirk that fuzzy matching genuinely cannot resolve — documented, not hidden).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.crosswalk import (  # noqa: E402
    build_crosswalk, crosswalk_stats, normalize_name,
)


def test_normalize_strips_suffixes_and_state_tags_symmetrically():
    assert normalize_name("WELLS FARGO & COMPANY") == "WELLS FARGO"
    assert normalize_name("WELLS FARGO & COMPANY/MN") == "WELLS FARGO"
    assert normalize_name("FLAGSTAR BANCORP INC") == "FLAGSTAR"
    assert normalize_name("FLAGSTAR BANK, NATIONAL ASSOCIATION") == "FLAGSTAR"


def test_normalize_handles_none_and_empty():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


def test_exact_match_after_normalization():
    holding_companies = {1120754: "WELLS FARGO & COMPANY"}
    sec_tickers = {72971: {"ticker": "WFC", "title": "WELLS FARGO & COMPANY/MN"}}
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["match_type"] == "exact"
    assert rows[0]["cik"] == 72971 and rows[0]["ticker"] == "WFC"


def test_exact_match_after_symmetric_suffix_stripping():
    """Flagstar's holding co was folded into its bank subsidiary post-merger — FDIC's
    'Bancorp' name and SEC's 'Bank, National Association' title normalize IDENTICALLY
    once industry words are stripped symmetrically. That collapse to 'exact' (not
    merely fuzzy) is itself the point: asymmetric suffix stripping would have missed it."""
    holding_companies = {1234: "FLAGSTAR BANCORP INC"}
    sec_tickers = {910073: {"ticker": "FLG", "title": "FLAGSTAR BANK, NATIONAL ASSOCIATION"}}
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["match_type"] == "exact"
    assert rows[0]["ticker"] == "FLG"


def test_high_confidence_fuzzy_match():
    """A minor one-letter typo in the core name (not a suffix word), close enough to
    trust automatically without being byte-identical after normalization."""
    holding_companies = {5555: "MIDWEST COMUNITY BANCORP"}   # typo: COMUNITY
    sec_tickers = {9999: {"ticker": "MWCB", "title": "MIDWEST COMMUNITY BANK"}}
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["match_type"] == "high_confidence"
    assert rows[0]["match_score"] >= 0.85


def test_dime_community_vs_commercial_is_a_documented_low_confidence_case():
    """A real naming discrepancy: FDIC says 'Community', SEC's title says
    'Commercial' for the same real company (ticker DCOM). Fuzzy matching alone
    correctly can NOT promote this to high confidence — that's the honest limit."""
    holding_companies = {1416523: "DIME COMMUNITY BANCSHARES INC"}
    sec_tickers = {846617: {"ticker": "DCOM", "title": "Dime Commercial Bancshares, Inc. /NY/"}}
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["match_type"] == "low_confidence"
    assert 0.60 <= rows[0]["match_score"] < 0.85
    assert rows[0]["ticker"] == "DCOM"   # still surfaced for human review, not dropped


def test_first_token_blocking_avoids_false_positive():
    """Regression test for a REAL bug found while building this: naive fuzzy matching
    (no blocking) picked 'Community Trust Bancorp Inc /KY/' — an unrelated Kentucky
    bank — over the real 'Dime Commercial Bancshares' for the 'Dime Community
    Bancshares' target, purely because 'Community Trust Bancorp' scored higher on
    raw character overlap (0.78 vs 0.69). Blocking on the first token (DIME vs
    COMMUNITY) excludes the impostor from consideration entirely."""
    holding_companies = {1416523: "DIME COMMUNITY BANCSHARES INC"}
    sec_tickers = {
        846617: {"ticker": "DCOM", "title": "Dime Commercial Bancshares, Inc. /NY/"},
        350852: {"ticker": "CTBI", "title": "COMMUNITY TRUST BANCORP INC /KY/"},
    }
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["ticker"] == "DCOM"          # the real match, not the impostor
    assert rows[0]["match_type"] == "low_confidence"


def test_no_candidate_below_low_confidence_floor():
    holding_companies = {1: "COMPLETELY UNRELATED ENTITY NAME"}
    sec_tickers = {2: {"ticker": "XYZ", "title": "NVIDIA CORP"}}
    rows = build_crosswalk(holding_companies, sec_tickers)
    assert rows[0]["match_type"] == "none" and rows[0]["cik"] is None


def test_stats_tally_all_tiers():
    rows = [
        {"match_type": "exact"}, {"match_type": "high_confidence"},
        {"match_type": "low_confidence"}, {"match_type": "none"}, {"match_type": "none"},
    ]
    s = crosswalk_stats(rows)
    assert s == {"total": 5, "exact": 1, "high_confidence": 1, "low_confidence": 1,
                "none": 2, "match_rate_pct": 60.0}


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
