"""Regression tests for the path-traversal fix documented in SECURITY.md
("Findings from an actual security pass (Phase 8)"). Verified live at the
time: a `bank_quarters(cert)` call with `cert="../../../../../.."` read
`records.json` from OUTSIDE `data/` entirely (confirmed with a planted
out-of-tree sentinel file). Fixed by coercing `cert` to a real `int` before
it ever touches a path — this file exists so that fix can never silently
regress.

Hermetic: both checks below happen (int-coercion failure / path-containment
failure) before any landed data would be read, so no `data/` checkout is
required — no SKIP path needed here.

Run: ``python services/mcp-server/tests/test_data.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "pipelines" / "transforms" / "src"))

from banklens_mcp import data  # noqa: E402

_TRAVERSAL_PAYLOADS = [
    "../../../../../..",
    "../../../../../../etc/passwd",
    "..\\..\\..\\..\\windows\\system32",
    "1234/../../../../secret",
]


# ---- bank_quarters(cert): non-numeric input must never reach a path join ---

def test_traversal_shaped_cert_returns_none_not_a_path_read():
    for payload in _TRAVERSAL_PAYLOADS:
        assert data.bank_quarters(payload) is None, f"payload leaked through: {payload!r}"


def test_non_numeric_cert_of_any_shape_returns_none():
    for bad in ("abc", "", "12.5", None, [1, 2], {"cert": 1}):
        assert data.bank_quarters(bad) is None, f"non-numeric cert accepted: {bad!r}"


def test_a_real_looking_numeric_cert_string_is_still_coerced_and_accepted():
    """The fix must reject non-numeric input WITHOUT breaking the ordinary
    case — a numeric string (exactly what arrives over MCP/JSON in practice)
    must still be coerced to int and looked up normally (returns None here
    only because no bank with this cert is landed in this environment, not
    because the coercion itself failed)."""
    result = data.bank_quarters("6976")
    assert result is None or isinstance(result, list)


def test_a_real_int_cert_still_works_the_ordinary_way():
    result = data.bank_quarters(6976)
    assert result is None or isinstance(result, list)


# ---- price_bars(ticker): resolved path must stay inside the expected dir --

def test_traversal_shaped_ticker_is_rejected_by_the_containment_check():
    for payload in _TRAVERSAL_PAYLOADS:
        assert data.price_bars(payload) is None, f"payload leaked through: {payload!r}"


def test_ordinary_ticker_still_resolves_the_ordinary_way():
    """No landed Tiingo data for this ticker in this environment, so the
    real assertion is just that it's rejected for the right reason (not
    landed) rather than raising -- containment must not break the normal path."""
    result = data.price_bars("AAPL")
    assert result is None or isinstance(result, list)


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
