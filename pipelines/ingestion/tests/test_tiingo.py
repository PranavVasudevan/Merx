"""Tiingo connector tests — request-building and response handling, no network,
no API key needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_ingestion.sources.tiingo import MissingApiKey, TiingoSource, get_api_key  # noqa: E402


def test_source_metadata():
    s = TiingoSource(api_key="fake")
    assert s.name == "tiingo.eod"
    assert s.license == "commercial-licensed"   # NOT public-domain, unlike FDIC/SEC


def test_get_api_key_raises_helpful_error(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    raised = False
    try:
        get_api_key()
    except MissingApiKey as e:
        raised = True
        assert "api.tiingo.com/account/api/token" in str(e)
    assert raised


def test_fetch_daily_prices_tags_ticker_and_source_url(monkeypatch):
    s = TiingoSource(api_key="fake")
    canned = [{"date": "2026-03-31T00:00:00.000Z", "close": 100.0, "open": 99.0,
              "high": 101.0, "low": 98.0, "volume": 1000}]
    monkeypatch.setattr(s, "_get", lambda url: canned)
    rows = s.fetch_daily_prices("WFC", start_date="2026-01-01")
    assert rows[0]["_ticker"] == "WFC"
    assert "WFC" in rows[0]["_source_url"] and "startDate=2026-01-01" in rows[0]["_source_url"]


def test_fetch_daily_prices_rejects_unexpected_shape(monkeypatch):
    s = TiingoSource(api_key="fake")
    monkeypatch.setattr(s, "_get", lambda url: {"error": "not found"})  # dict, not a list
    raised = False
    try:
        s.fetch_daily_prices("BOGUS")
    except RuntimeError as e:
        raised = True
        assert "unexpected shape" in str(e)
    assert raised


def test_no_query_params_means_no_query_string(monkeypatch):
    s = TiingoSource(api_key="fake")
    captured = {}
    def fake_get(url):
        captured["url"] = url
        return []
    monkeypatch.setattr(s, "_get", fake_get)
    s.fetch_daily_prices("ZION")
    assert captured["url"] == "https://api.tiingo.com/tiingo/daily/ZION/prices"


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
                        def delenv(self, k, raising=True):
                            import os
                            os.environ.pop(k, None)
                    fn(_MP())
                else:
                    fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
