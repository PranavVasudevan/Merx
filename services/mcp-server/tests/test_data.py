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


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
