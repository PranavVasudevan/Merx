"""Market price transform tests — Silver mapping + Gold derived metrics, using
a small synthetic OHLCV series with known statistical properties (no network,
no Tiingo key needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_transforms.market import (  # noqa: E402
    daily_returns, fifty_two_week_range, price_snapshot,
    realized_volatility_annualized, to_price_bar,
)

RAW_BAR = {
    "date": "2026-03-31T00:00:00.000Z", "open": 99.0, "high": 101.5, "low": 98.5,
    "close": 100.0, "volume": 1_200_000, "adjOpen": 99.0, "adjHigh": 101.5,
    "adjLow": 98.5, "adjClose": 100.0, "adjVolume": 1_200_000, "divCash": 0.0,
    "splitFactor": 1.0, "_ticker": "TEST", "_source_url": "https://...",
}


def _series(prices: list[float]) -> list[dict]:
    """Build a minimal ascending bar series from a list of adj_close prices."""
    bars = []
    for i, p in enumerate(prices):
        bars.append({"ticker": "TEST", "date": f"2026-01-{i+1:02d}", "open": p, "high": p * 1.01,
                    "low": p * 0.99, "close": p, "volume": 1000, "adj_close": p,
                    "adj_volume": 1000, "div_cash": 0.0, "split_factor": 1.0})
    return bars


def test_to_price_bar_maps_fields_and_truncates_date():
    row = to_price_bar(RAW_BAR)
    assert row["date"] == "2026-03-31"          # timestamp stripped to just the date
    assert row["ticker"] == "TEST"
    assert row["close"] == 100.0 and row["adj_close"] == 100.0


def test_daily_returns_simple_case():
    bars = _series([100, 110, 99])  # +10%, then -10%
    returns = daily_returns(bars)
    assert len(returns) == 2
    assert abs(returns[0] - 0.10) < 1e-9
    assert abs(returns[1] - (-0.10)) < 1e-9


def test_daily_returns_needs_at_least_two_bars():
    assert daily_returns(_series([100])) == []
    assert daily_returns([]) == []


def test_realized_volatility_zero_for_flat_prices():
    bars = _series([100.0] * 40)  # no movement at all -> zero volatility
    assert realized_volatility_annualized(bars) == 0.0


def test_realized_volatility_positive_for_moving_prices():
    prices = [100, 102, 98, 105, 95, 103, 97, 101, 99, 104] * 4
    vol = realized_volatility_annualized(_series(prices))
    assert vol is not None and vol > 0


def test_realized_volatility_none_with_insufficient_history():
    assert realized_volatility_annualized(_series([100])) is None
    assert realized_volatility_annualized([]) is None


def test_fifty_two_week_range():
    prices = list(range(50, 150))  # ascending 50..149
    r = fifty_two_week_range(_series([float(p) for p in prices]))
    assert r["week52_low"] is not None and r["week52_high"] is not None
    assert r["week52_high"] >= r["week52_low"]


def test_price_snapshot_empty_series_is_all_none():
    snap = price_snapshot([])
    assert snap["ticker"] is None and snap["close"] is None


def test_price_snapshot_computes_1d_change():
    bars = _series([100, 105])  # +5%
    snap = price_snapshot(bars)
    assert snap["ticker"] == "TEST"
    assert snap["close"] == 105
    assert abs(snap["change_1d_pct"] - 5.0) < 1e-6


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
