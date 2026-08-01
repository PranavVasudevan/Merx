"""Branch-footprint tests — grid-cell aggregation and overlap, using synthetic
coordinates plus a regression fixture from a REAL finding (Citizens Bank, CERT
57957: FDIC's STALP/CITY/ADDRESS fields are frozen at the HQ address for every
branch, while SIMS_LATITUDE/SIMS_LONGITUDE genuinely span the whole country)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.footprint import (  # noqa: E402
    build_footprints, cell_overlap, county_concentration, county_deposit_table,
    county_key, deposit_weighted_overlap, grid_cell, herfindahl,
)


def _branch(cert, lat, lon, dep_thousands=1000, city="ANY", stalp="XX"):
    return {"CERT": cert, "SIMS_LATITUDE": lat, "SIMS_LONGITUDE": lon,
           "DEPSUMBR": dep_thousands, "CITY": city, "STALP": stalp,
           "ADDRESS": "1 Main St"}


def test_grid_cell_buckets_nearby_points_together():
    a = grid_cell(40.7128, -74.0060)     # NYC
    b = grid_cell(40.7300, -73.9950)     # a few blocks away
    c = grid_cell(34.0522, -118.2437)    # LA — far away
    assert a == b
    assert a != c


def test_build_footprints_groups_by_cert_and_computes_centroid():
    records = [_branch(1, 40.71, -74.00), _branch(1, 40.72, -74.01), _branch(2, 34.05, -118.24)]
    fps = build_footprints(records)
    assert fps[1]["branch_count"] == 2
    assert fps[2]["branch_count"] == 1
    assert fps[1]["centroid"][0] == (40.71 + 40.72) / 2


def test_regression_stuck_hq_address_does_not_corrupt_footprint():
    """Regression test for the REAL Citizens Bank finding: even though every branch
    record reports the identical HQ city/address/state, DISTINCT real coordinates
    must still produce a MULTI-CELL footprint (proving the code never relies on the
    unreliable STALP/CITY/ADDRESS fields — only on coordinates)."""
    # Real coordinate pairs seen live for CERT 57957 (Citizens Bank), all tagged
    # "Providence, RI, 1 Citizens Plz" in FDIC's own (unreliable) fields.
    records = [
        _branch(57957, 41.8273839968384, -71.4107620303569, city="Providence", stalp="RI"),
        _branch(57957, 43.101012843242, -77.537251635239, city="Providence", stalp="RI"),
        _branch(57957, 42.712996985164, -83.0309389825123, city="Providence", stalp="RI"),
        _branch(57957, 40.4309709977503, -74.388774025435, city="Providence", stalp="RI"),
    ]
    fps = build_footprints(records)
    fp = fps[57957]
    assert fp["branch_count"] == 4
    assert len(fp["cells"]) == 4, "distinct real coordinates must yield distinct cells despite identical city/state fields"


def test_cell_overlap_full_and_none():
    fp_a = build_footprints([_branch(1, 40.71, -74.00), _branch(1, 40.72, -74.00)])[1]
    fp_b = build_footprints([_branch(2, 40.71, -74.00)])[2]        # same cell as A's first branch
    fp_c = build_footprints([_branch(3, 34.05, -118.24)])[3]       # totally different market

    assert cell_overlap(fp_a, fp_b) is not None and cell_overlap(fp_a, fp_b) > 0
    assert cell_overlap(fp_a, fp_c) == 0.0
    assert cell_overlap(fp_a, None) is None
    assert cell_overlap(None, fp_b) is None


def test_deposit_weighted_overlap_favors_shared_big_markets():
    records = [
        _branch(1, 40.71, -74.00, dep_thousands=100_000),   # bank 1: big NYC branch
        _branch(2, 40.71, -74.00, dep_thousands=90_000),    # bank 2: also big, same cell
        _branch(2, 34.05, -118.24, dep_thousands=10_000),   # bank 2: small LA branch, no overlap
    ]
    fps = build_footprints(records)
    overlap = deposit_weighted_overlap(fps[1], fps[2])
    assert overlap is not None and 0 < overlap < 1
    # shared cell deposits: min(100k,90k)=90k; union = 100k+90k+10k-90k = 110k -> 90/110
    assert abs(overlap - round(90_000 / 110_000, 4)) < 1e-4


def _br(cert, fips, dep_thousands=1000, name="Somewhere", state="XX"):
    """A branch row carrying REAL branch-level geography (STCNTYBR), which is what
    the landed SOD has after the connector fix."""
    return {"CERT": cert, "STCNTYBR": fips, "CNTYNAMB": name, "STALPBR": state,
            "DEPSUMBR": dep_thousands}


def test_county_key_zero_pads_fips():
    """FDIC returns STCNTYBR as an int, so San Diego (06073) arrives as 6073.
    Without padding it would collide in string space with 60730 and sort wrongly."""
    assert county_key({"STCNTYBR": 6073}) == "06073"
    assert county_key({"STCNTYBR": 46099}) == "46099"
    assert county_key({"STCNTYBR": None}) is None
    assert county_key({}) is None


def test_footprint_prefers_real_county_over_coordinate_grid():
    records = [_br(1, 6073), _br(1, 6073), _br(1, 46099)]
    fp = build_footprints(records)[1]
    assert fp["geo_basis"] == "county"
    assert fp["cells"] == {"06073", "46099"}      # two distinct real markets
    assert fp["branch_count"] == 3


def test_footprint_falls_back_to_grid_without_county():
    """Synthetic/legacy rows with coordinates but no FIPS must still work."""
    fp = build_footprints([_branch(1, 40.71, -74.00), _branch(1, 34.05, -118.24)])[1]
    assert fp["geo_basis"] == "grid"
    assert len(fp["cells"]) == 2


def test_unplaceable_branch_still_counted_but_not_placed():
    """A branch with neither county nor coordinates must not silently vanish from
    branch_count — that would misstate network size."""
    fp = build_footprints([_br(1, 6073), {"CERT": 1, "DEPSUMBR": 500}])[1]
    assert fp["branch_count"] == 2
    assert fp["cells"] == {"06073"}


def test_herfindahl_uses_the_doj_0_to_10000_convention():
    """A monopoly is 10,000, not 1.0 — the published Fed/DOJ screening thresholds
    (1,800 concentrated) only apply on this scale."""
    assert herfindahl([100.0]) == 10000.0
    assert herfindahl([50.0, 50.0]) == 5000.0
    assert herfindahl([25.0, 25.0, 25.0, 25.0]) == 2500.0


def test_county_concentration_shares_and_hhi():
    # one county, two banks, 75/25 split -> HHI = 75^2 + 25^2 = 6250
    table = county_deposit_table([_br(1, 6073, 750), _br(2, 6073, 250)])
    conc = county_concentration(table["06073"])
    assert conc["hhi"] == 6250.0
    assert [s["cert"] for s in conc["shares"]] == [1, 2]      # ranked by deposits
    assert conc["shares"][0]["share_pct"] == 75.0
    assert conc["total_deposits"] == 1_000_000                # thousands -> USD


def test_county_concentration_handles_zero_deposit_market():
    """2.9% of real SOD rows report $0 deposits; a county of only those must not
    divide by zero or fabricate a share."""
    table = county_deposit_table([_br(1, 6073, 0)])
    conc = county_concentration(table["06073"])
    assert conc["hhi"] is None and conc["shares"] == []


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
