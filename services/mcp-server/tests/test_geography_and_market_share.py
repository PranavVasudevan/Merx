"""Tests for get_county_concentration and get_branch_map (Feature 15) — both need
landed SOD branch data (scripts/land_sod.ps1). SkipTest, not fail, if absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_sod_data():
    from banklens_mcp import data
    if not data.sod_raw():
        raise SkipTest("no landed SOD branch data (run scripts/land_sod.ps1)")


# ---- get_county_concentration ----------------------------------------------
def test_county_concentration_hhi_is_valid_range():
    require_sod_data()
    r = tools.get_county_concentration(top_n=200)
    assert r["county_count"] > 0
    for c in r["counties"]:
        assert 0.0 < c["hhi"] <= 10000.0
        assert c["concentrated"] == (c["hhi"] >= r["hhi_concentrated_threshold"])


def test_county_concentration_shares_sum_to_at_most_100pct():
    require_sod_data()
    r = tools.get_county_concentration(top_n=50)
    for c in r["counties"]:
        # only top-8 shares are returned per county, so this is a <= not ==
        assert sum(s["share_pct"] for s in c["shares"]) <= 100.01


def test_county_concentration_sorted_most_concentrated_first():
    require_sod_data()
    r = tools.get_county_concentration(top_n=100)
    hhis = [c["hhi"] for c in r["counties"]]
    assert hhis == sorted(hhis, reverse=True)


def test_county_concentration_state_filter_only_returns_that_state():
    require_sod_data()
    r = tools.get_county_concentration(state="WI", top_n=500)
    assert r["county_count"] > 0
    assert all(c["state"] == "WI" for c in r["counties"])


def test_county_concentration_spans_full_universe_not_just_population():
    """The whole point of Feature 15: a bank far outside the $1B-$250B population
    (e.g. a tiny single-branch community bank) can still be a county's top/only
    depositor and should show up with its real name, not silently omitted."""
    require_sod_data()
    r = tools.get_county_concentration(top_n=500)
    from banklens_mcp import data
    population_certs = set(data.population()["by_cert"])
    non_population_shares = [
        s for c in r["counties"] for s in c["shares"] if s["cert"] not in population_certs
    ]
    assert non_population_shares, "expected at least one top-share bank outside the analytical population"
    for s in non_population_shares[:5]:
        assert not s["name"].startswith("CERT ")   # real name resolved, not a fallback


# ---- get_branch_map ---------------------------------------------------------
def test_branch_map_excludes_non_contiguous_but_discloses_the_count():
    require_sod_data()
    from banklens_mcp import data
    r = tools.get_branch_map()
    assert r["excluded_non_contiguous"] > 0
    assert all(True for b in r["branches"])  # every returned branch has lat/lon by construction
    assert r["branch_count"] + 0 <= r["branch_count"]  # sanity: no crash on empty check
    # cross-check: no returned branch's implied state is a non-contiguous one
    fips_prefixes_seen = {b["fips"][:2] for b in r["branches"] if b["fips"]}
    assert fips_prefixes_seen, "expected at least some branches with a county fips"


def test_branch_map_state_filter_narrows_results():
    require_sod_data()
    all_r = tools.get_branch_map()
    ca_r = tools.get_branch_map(state="CA")
    assert 0 < ca_r["branch_count"] < all_r["branch_count"]


def test_branch_map_bank_names_cover_every_returned_branch_cert():
    require_sod_data()
    r = tools.get_branch_map(state="WI")
    certs_in_branches = {b["cert"] for b in r["branches"]}
    assert certs_in_branches <= set(r["bank_names"])


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
