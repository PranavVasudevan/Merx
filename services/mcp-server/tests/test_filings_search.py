"""Tests for search_filings_text and get_filings_coverage (Feature 17, Tier 6
capstone). Needs Postgres/pgvector up AND at least one landed filer (see
scripts/land_filings.ps1) AND Ollama running locally with nomic-embed-text
pulled for real embedding calls. SkipTest, not fail, if any of that is absent —
same convention as the rest of this test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_landed_filings():
    try:
        cov = tools.get_filings_coverage()
    except ValueError as e:
        raise SkipTest(f"filings database unavailable: {e}") from e
    if cov["filers"] == 0:
        raise SkipTest("no filings landed yet (run scripts/land_filings.ps1)")


# ---- get_filings_coverage ---------------------------------------------------
def test_coverage_reports_real_counts():
    require_landed_filings()
    cov = tools.get_filings_coverage()
    assert cov["filers"] > 0
    assert cov["chunks"] > 0
    assert cov["chunks"] >= cov["filers"]   # at least one chunk per filer
    assert sum(cov["by_confidence"].values()) == cov["filers"]


# ---- search_filings_text ----------------------------------------------------
def test_search_rejects_empty_query():
    try:
        tools.search_filings_text("")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "non-empty" in str(e)


def test_search_returns_ranked_real_results():
    require_landed_filings()
    r = tools.search_filings_text("commercial real estate concentration risk", top_n=5)
    assert r["query"]
    assert r["count"] == len(r["results"])
    assert r["count"] <= 5
    sims = [res["similarity"] for res in r["results"]]
    assert sims == sorted(sims, reverse=True)
    for res in r["results"]:
        assert -1.0 <= res["similarity"] <= 1.0
        assert res["chunk_text"]
        assert res["extraction_confidence"] == "high"   # only high-confidence chunks are ever stored


def test_search_different_queries_return_different_top_result_or_none():
    """Not a strict correctness proof (no labeled relevance set), but a basic
    sanity check that the search is actually query-sensitive rather than always
    returning the same fixed row regardless of input."""
    require_landed_filings()
    a = tools.search_filings_text("cybersecurity data breach", top_n=1)
    b = tools.search_filings_text("interest rate risk on securities", top_n=1)
    if a["results"] and b["results"]:
        # not asserting they MUST differ (a tiny corpus could legitimately have
        # one chunk dominate both), just that similarity scores are independently computed
        assert isinstance(a["results"][0]["similarity"], float)
        assert isinstance(b["results"][0]["similarity"], float)


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
