"""FDIC SOD connector tests — pagination logic, no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_ingestion.sources.sod import SodSource  # noqa: E402


def test_source_metadata():
    s = SodSource()
    assert s.name == "fdic.sod"
    assert s.license == "public-domain-us-gov"     # keyless, unlike Tiingo


def test_fetch_all_branches_paginates_until_total_reached(monkeypatch):
    """total must exceed one page (10,000) to actually exercise multi-page pagination —
    real total here is 20,001, needing exactly 3 fetches (10000+10000+1)."""
    s = SodSource()
    TOTAL = 20001
    pages = {
        0: ([{"CERT": 1}] * 10000, TOTAL),
        10000: ([{"CERT": 2}] * 10000, TOTAL),
        20000: ([{"CERT": 3}] * 1, TOTAL),
    }
    calls = []

    def fake_get_page(year, offset):
        calls.append(offset)
        return pages[offset]
    monkeypatch.setattr(s, "_get_page", fake_get_page)

    rows = s.fetch_all_branches(2025)
    assert len(rows) == TOTAL
    assert calls == [0, 10000, 20000]


def test_fetch_all_branches_stops_on_empty_page(monkeypatch):
    """Defensive: an empty page (even if `total` looks wrong) must not loop forever."""
    s = SodSource()

    def fake_get_page(year, offset):
        return ([], 999999) if offset == 0 else ([], 999999)
    monkeypatch.setattr(s, "_get_page", fake_get_page)

    rows = s.fetch_all_branches(2025)
    assert rows == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                import inspect
                if "monkeypatch" in inspect.signature(fn).parameters:
                    class _MP:
                        def setattr(self, obj, attr, val):
                            setattr(obj, attr, val)
                    fn(_MP())
                else:
                    fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
