"""FDIC BankFind connector — hermetic only (envelope parsing, checksum-relevant
row/URL attachment, and the single-request pagination-ceiling guard). No live
FDIC network calls in CI, same convention as `.github/workflows/ci.yml` and
`services/ingestion/src/sources/fdic.rs` both already describe. `_get()` (the
only method that touches the network) is monkeypatched per-instance on every
test here — never called for real.

Run: ``python pipelines/ingestion/tests/test_fdic.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_ingestion.sources.fdic import FdicSource  # noqa: E402


def envelope(rows: list[dict], total: int | None = None) -> dict:
    """FDIC's real response shape: {"data": [{"data": {...}, "score": ...}, ...],
    "meta": {"total": N}}."""
    payload: dict = {"data": [{"data": r, "score": 1.0} for r in rows]}
    if total is not None:
        payload["meta"] = {"total": total}
    return payload


# ---- envelope parsing (_unwrap) -------------------------------------------

def test_unwrap_extracts_the_inner_data_dict_from_each_row():
    payload = envelope([{"CERT": 1}, {"CERT": 2}])
    assert FdicSource._unwrap(payload) == [{"CERT": 1}, {"CERT": 2}]


def test_unwrap_defaults_a_row_missing_its_data_key_to_empty_dict():
    payload = {"data": [{"score": 1.0}]}   # malformed row, no "data" key at all
    assert FdicSource._unwrap(payload) == [{}]


def test_unwrap_on_an_empty_payload_returns_an_empty_list():
    assert FdicSource._unwrap({}) == []
    assert FdicSource._unwrap({"data": []}) == []


# ---- get_institution --------------------------------------------------

def test_get_institution_raises_lookup_error_when_no_rows_returned():
    src = FdicSource()
    src._get = lambda endpoint, params: (envelope([]), "https://fake/institutions")
    try:
        src.get_institution(999999)
        raise AssertionError("expected LookupError")
    except LookupError:
        pass


def test_get_institution_attaches_the_real_source_url_to_the_row():
    src = FdicSource()
    url = "https://banks.data.fdic.gov/api/institutions?filters=CERT%3A6976&fields=NAME&limit=1"
    src._get = lambda endpoint, params: (envelope([{"CERT": 6976, "NAME": "Testbank"}]), url)
    row = src.get_institution(6976)
    assert row["_source_url"] == url
    assert row["CERT"] == 6976


# ---- fetch: per-quarter financials -----------------------------------------

def test_fetch_attaches_the_source_url_to_every_returned_row():
    src = FdicSource()
    url = "https://fake/financials"
    src._get = lambda endpoint, params: (
        envelope([{"CERT": 1, "REPDTE": "20260101"}, {"CERT": 1, "REPDTE": "20251001"}]), url,
    )
    rows = src.fetch(1, quarters=2)
    assert len(rows) == 2
    assert all(r["_source_url"] == url for r in rows)


# ---- fetch_population: the single-request pagination ceiling --------------

def test_fetch_population_raises_when_the_response_is_silently_truncated():
    """meta.total > len(returned rows) means the population slice outgrew the
    10,000-row single-request assumption — must fail loudly, not silently hand
    back a partial population as if it were the whole thing."""
    src = FdicSource()
    src._get = lambda endpoint, params: (
        envelope([{"CERT": i} for i in range(5)], total=10), "https://fake/financials",
    )
    try:
        src.fetch_population("20260101")
        raise AssertionError("expected RuntimeError for a truncated population")
    except RuntimeError as e:
        assert "10,000-row" in str(e) or "outgrew" in str(e)


def test_fetch_population_succeeds_when_row_count_matches_total():
    src = FdicSource()
    rows_in = [{"CERT": i} for i in range(5)]
    src._get = lambda endpoint, params: (envelope(rows_in, total=5), "https://fake/financials")
    rows, url = src.fetch_population("20260101")
    assert len(rows) == 5
    assert all(r["_source_url"] == url for r in rows)


def test_fetch_population_succeeds_when_meta_total_is_absent():
    """Some responses may omit meta.total entirely -- absence must not be
    misread as truncation (only total_present AND total > len(rows) should
    raise)."""
    src = FdicSource()
    src._get = lambda endpoint, params: (
        envelope([{"CERT": 1}]), "https://fake/financials",   # no `total` kwarg -> no meta key
    )
    rows, _ = src.fetch_population("20260101")
    assert len(rows) == 1


def test_fetch_population_passes_asset_bounds_in_thousands_through_the_filter_string():
    src = FdicSource()
    captured = {}

    def fake_get(endpoint, params):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return envelope([], total=0), "https://fake/financials"

    src._get = fake_get
    src.fetch_population("20260101", min_assets_k=1_000_000, max_assets_k=250_000_000)
    assert captured["endpoint"] == "financials"
    assert "REPDTE:20260101" in captured["params"]["filters"]
    assert "1000000" in captured["params"]["filters"]
    assert "250000000" in captured["params"]["filters"]


# ---- fetch_failures: same pagination guard, different endpoint ------------

def test_fetch_failures_raises_when_the_response_is_silently_truncated():
    src = FdicSource()
    src._get = lambda endpoint, params: (
        envelope([{"CERT": i} for i in range(3)], total=4115), "https://fake/failures",
    )
    try:
        src.fetch_failures()
        raise AssertionError("expected RuntimeError for a truncated failures list")
    except RuntimeError:
        pass


def test_fetch_failures_attaches_source_url_and_matches_when_total_agrees():
    src = FdicSource()
    rows_in = [{"CERT": 24735, "NAME": "Silicon Valley Bank"}]
    src._get = lambda endpoint, params: (envelope(rows_in, total=1), "https://fake/failures")
    rows, url = src.fetch_failures()
    assert rows[0]["CERT"] == 24735
    assert rows[0]["_source_url"] == url


# ---- construction / identity -----------------------------------------------

def test_default_user_agent_identifies_the_project_not_a_generic_client():
    src = FdicSource()
    assert "BankLens" in src.user_agent


def test_custom_user_agent_is_honored_not_overridden():
    src = FdicSource(user_agent="custom-agent/1.0")
    assert src.user_agent == "custom-agent/1.0"


def test_license_tag_marks_this_as_public_domain_us_government_data():
    assert FdicSource.license == "public-domain-us-gov"


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
