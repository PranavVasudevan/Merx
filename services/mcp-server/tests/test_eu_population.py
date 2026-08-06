"""EU (EBA Transparency Exercise) population merge — real live-landed data, same
"SKIP if not landed, don't fail" posture test_mcp.py uses for Bronze-dependent
tests. See pipelines/transforms/src/banklens_transforms/silver_eba.py and
services/mcp-server/src/banklens_mcp/data.py's `_eu_silver`/`population` for what
this is exercising: currency conversion, the synthetic cert_number namespace, and
graceful degradation (no peer cluster, no branch footprint, no stress test) for a
bank whose disclosure genuinely doesn't cover those things.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import data, tools  # noqa: E402


class SkipTest(Exception):
    pass


def require_eu_landed():
    if not data._eu_silver():
        raise SkipTest("no landed EBA data under data/bronze/source=eba "
                       "(run scripts/land_eba.ps1)")


def test_eu_banks_appear_in_population_with_country_set():
    require_eu_landed()
    gold = data.population()["gold"]
    eu = [g for g in gold if g.get("country") not in (None, "US")]
    assert eu
    assert all(g["cert_number"] >= 900_000_000 for g in eu)


def test_eu_bank_cert_numbers_never_collide_with_a_real_us_cert():
    require_eu_landed()
    gold = data.population()["gold"]
    us_certs = {g["cert_number"] for g in gold if g.get("country") == "US"}
    eu_certs = {g["cert_number"] for g in gold if g.get("country") not in (None, "US")}
    assert not (us_certs & eu_certs)


def test_eu_bank_has_no_fabricated_peer_cluster():
    """EBA doesn't disclose the loan-mix/deposit fields clustering runs on — an EU
    bank must come back with cluster_id=None, never an imputed-mean assignment
    dressed up as a real behavioral match."""
    require_eu_landed()
    gold = data.population()["gold"]
    eu = next(g for g in gold if g.get("country") not in (None, "US"))
    result = tools.get_peer_cluster(eu["cert_number"])
    assert result["cluster_id"] is None
    assert result["cluster_label"] is None
    assert result["sample_peers"] == []


def test_eu_bank_capital_ratios_are_not_still_raw_fractions():
    """Regression guard for the live-verified EBA quirk: ratios arrive as raw
    fractions (0.18 = 18%), not already-percentages like FDIC's. NOT an upper-bound
    check — Nordic public-sector covered-bond funders (Kommuninvest, Kuntarahoitus)
    genuinely report CET1 in the 90-350% range live (their book is almost entirely
    0%-risk-weighted sovereign/municipal exposure, so RWA is <5% of total assets —
    verified against their own raw RWA/assets figures), so any fixed ceiling is the
    wrong invariant and would be a false alarm on real data, not a caught bug. The
    one thing that IS always true regardless of institution type: an unscaled
    fraction is always < 1.0 (no real bank's CET1 rounds to under 1%), so every
    landed value being > 1.0 is real evidence the *100 scaling in sources/eba.py
    ran, without asserting a made-up ceiling on how large a legitimate ratio gets."""
    require_eu_landed()
    gold = data.population()["gold"]
    eu_with_cet1 = [g for g in gold
                    if g.get("country") not in (None, "US") and g.get("cet1_ratio") is not None]
    assert eu_with_cet1
    for g in eu_with_cet1:
        assert g["cet1_ratio"] > 1.0, \
            f"{g['name']}: CET1 {g['cet1_ratio']} looks like an unscaled fraction"


def test_list_banks_country_filter_returns_only_that_country():
    require_eu_landed()
    result = tools.list_banks(country="DE", limit=50)
    assert result["banks"]
    assert all(b["country"] == "DE" for b in result["banks"])


def test_compare_banks_across_us_and_eu_does_not_crash():
    require_eu_landed()
    gold = data.population()["gold"]
    us_cert = next(g["cert_number"] for g in gold if g.get("country") == "US")
    eu_cert = next(g["cert_number"] for g in gold if g.get("country") not in (None, "US"))
    result = tools.compare_banks([us_cert, eu_cert])
    assert len(result["banks"]) == 2


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
