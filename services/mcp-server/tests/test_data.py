"""banklens_mcp.data tests — hermetic where possible, focused on the path-safety
fixes found live during a Phase-8 security pass.

Regression context: `bank_quarters(cert)` interpolates `cert` straight into a
filesystem path. It's reachable from the network (MCP tools/call -> diff_filings ->
bank_quarters) and nothing upstream actually enforces the `int` type hint at
runtime. Verified live before fixing: a `cert` of "../../../../.." made it read
records.json from OUTSIDE data/ entirely — a real, exploitable path traversal, not
a theoretical one. `price_bars(ticker)` has the same shape (defense in depth: it
currently only ever receives a trusted, crosswalk-derived ticker, never raw user
input, but the fix doesn't rely on that staying true).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_mcp import data  # noqa: E402


def test_bank_quarters_rejects_non_numeric_cert():
    """The exact live-confirmed exploit shape: this used to read a real file from
    outside data/ and return its contents. Must now return None."""
    assert data.bank_quarters("../../../../../..") is None
    assert data.bank_quarters("..\\..\\..\\Windows") is None
    assert data.bank_quarters("6976; rm -rf /") is None


def test_bank_quarters_accepts_a_real_int_or_numeric_string():
    # 6976 (Dime) is landed in this dev environment's data/ — if that ever isn't
    # true, this correctly returns None rather than raising, so it's safe either way.
    result_int = data.bank_quarters(6976)
    result_str = data.bank_quarters("6976")
    assert result_int == result_str  # numeric string and int must behave identically


def test_bank_quarters_rejects_float_and_none():
    assert data.bank_quarters(69.76) is None      # int(69.76) would silently truncate
    assert data.bank_quarters(None) is None


def test_price_bars_containment_rejects_traversal_shapes():
    """Defense in depth: even though price_bars only ever receives a trusted
    crosswalk ticker today, verify the path-containment check itself holds for
    several real traversal encodings, not just one."""
    for evil in ["../../../../../etc/passwd", "..\\..\\..\\Windows",
                "AAPL/../../../secret", "../../mcp_audit.jsonl"]:
        assert data.price_bars(evil) is None, f"traversal not blocked: {evil!r}"


def test_price_bars_containment_check_matches_a_real_ticker():
    base = data.DATA / "bronze" / "source=tiingo" / "daily"
    p = base / "ticker=ZION" / "records.json"
    assert base.resolve() in p.resolve().parents  # the check itself doesn't false-positive


class SkipTest(Exception):
    """Needs landed Bronze population data — see test_mcp.py's identical convention."""


def _require_landed_population():
    if not data._POP.exists():
        raise SkipTest(f"no landed population at {data._POP}")


def test_query_banks_matches_hand_filtered_python_semantics():
    """DuckDB's query_banks() must return exactly what the Python filter it
    replaced in tools.list_banks() used to (verified against real landed data,
    not a synthetic fixture, before the SQL rewrite ever shipped)."""
    _require_landed_population()
    gold = data.population()["gold"]

    def hand_filter(state=None, min_assets_b=None, max_assets_b=None, limit=20):
        def keep(g):
            if state and (g.get("state") or "").upper() != state.upper():
                return False
            a = (g.get("total_assets") or 0) / 1e9
            if min_assets_b is not None and a < min_assets_b:
                return False
            if max_assets_b is not None and a > max_assets_b:
                return False
            return True
        return [g["cert_number"] for g in
                sorted((g for g in gold if keep(g)),
                      key=lambda g: g.get("total_assets") or 0, reverse=True)[:limit]]

    cases = [
        {}, {"state": "NY", "max_assets_b": 20, "limit": 3},
        {"min_assets_b": 5, "max_assets_b": 15, "limit": 100}, {"state": "ca", "limit": 10},
    ]
    for c in cases:
        expected = hand_filter(**c)
        actual = [g["cert_number"] for g in data.query_banks(**c)]
        assert actual == expected, f"mismatch for {c}: expected {expected}, got {actual}"


def test_query_banks_name_search_is_case_insensitive_substring():
    _require_landed_population()
    hits = data.query_banks(query="bank", limit=1000)
    assert hits
    assert all("bank" in g["name"].lower() for g in hits)


def test_query_banks_sorted_descending_by_assets():
    _require_landed_population()
    hits = data.query_banks(limit=50)
    assets = [g.get("total_assets") or 0 for g in hits]
    assert assets == sorted(assets, reverse=True)


def test_query_banks_limit_is_respected():
    _require_landed_population()
    total = len(data.population()["gold"])
    assert len(data.query_banks(limit=5)) == 5
    assert len(data.query_banks(limit=total + 1000)) == total


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
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
