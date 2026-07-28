"""Market price data — Silver normalization + Gold derived metrics for the quant
terminal's candlestick charts. Feeds the `get_price_candles` MCP tool.

Silver grain: one row per (ticker, trading day). Gold adds realized volatility and
52-week range so the terminal can show more than a bare OHLCV series.

NOTE on licensing: unlike FDIC/SEC (public-domain), Tiingo's data is commercially
licensed — see config/sources.yaml. The MCP/serving layer should keep this in mind
if it's ever exposed for bulk export rather than display.
"""

from __future__ import annotations

import math


def to_price_bar(raw: dict) -> dict:
    """Map one raw Tiingo EOD record to a canonical Silver row."""
    date = str(raw.get("date", ""))[:10]  # "2024-01-02T00:00:00.000Z" -> "2024-01-02"
    return {
        "ticker": raw.get("_ticker"),
        "date": date,
        "open": raw.get("open"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "close": raw.get("close"),
        "volume": raw.get("volume"),
        "adj_close": raw.get("adjClose"),
        "adj_volume": raw.get("adjVolume"),
        "div_cash": raw.get("divCash"),
        "split_factor": raw.get("splitFactor"),
        "_source": "tiingo.eod",
    }


def daily_returns(bars_asc: list[dict]) -> list[float]:
    """Simple day-over-day % returns on adjusted close, oldest-first input."""
    out = []
    for i in range(1, len(bars_asc)):
        prev, cur = bars_asc[i - 1]["adj_close"], bars_asc[i]["adj_close"]
        if prev and cur and prev > 0:
            out.append((cur - prev) / prev)
    return out


def realized_volatility_annualized(bars_asc: list[dict], window: int = 30) -> float | None:
    """Annualized realized volatility (stdev of daily returns * sqrt(252)) over the
    most recent `window` trading days. None if there isn't enough history yet."""
    returns = daily_returns(bars_asc[-(window + 1):]) if len(bars_asc) > window else daily_returns(bars_asc)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 2)  # as a percentage


def fifty_two_week_range(bars_asc: list[dict]) -> dict:
    """52-week high/low off the last ~252 trading days (or all available if fewer)."""
    window = bars_asc[-252:] if len(bars_asc) > 252 else bars_asc
    highs = [b["high"] for b in window if b.get("high") is not None]
    lows = [b["low"] for b in window if b.get("low") is not None]
    return {"week52_high": max(highs) if highs else None,
           "week52_low": min(lows) if lows else None}


def price_snapshot(bars_asc: list[dict]) -> dict:
    """A single-row Gold summary for the latest trading day — what a bank-profile
    view or KPI tile wants, without needing the full candle series."""
    if not bars_asc:
        return {"ticker": None, "as_of": None, "close": None, "change_1d_pct": None,
               "volatility_30d_pct": None, "week52_high": None, "week52_low": None}
    latest = bars_asc[-1]
    prev = bars_asc[-2] if len(bars_asc) > 1 else None
    change_1d = None
    if prev and prev.get("adj_close") and latest.get("adj_close"):
        change_1d = round((latest["adj_close"] - prev["adj_close"]) / prev["adj_close"] * 100, 2)
    return {
        "ticker": latest["ticker"], "as_of": latest["date"], "close": latest["close"],
        "change_1d_pct": change_1d,
        "volatility_30d_pct": realized_volatility_annualized(bars_asc, window=30),
        **fifty_two_week_range(bars_asc),
    }
