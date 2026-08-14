"""Market price data — Silver normalization + Gold derived metrics for the quant
terminal's candlestick charts. Feeds the `get_price_candles` MCP tool.

Silver grain: one row per (ticker, trading day). Gold adds realized volatility and
52-week range so the terminal can show more than a bare OHLCV series.

E2 (docs/audit/04-remediation-prompts.md) adds the CROSS-bank primitives below
(rebased series, max drawdown, per-date return series for correlation/beta) —
the minimum real computation `get_market_overview` needs to power the /market
page's relative-performance chart, returns/vol scatter, correlation matrix and
metrics table, out of real landed Tiingo candles only.

NOTE on licensing: unlike FDIC/SEC (public-domain), Tiingo's data is commercially
licensed — see config/sources.yaml. The MCP/serving layer should keep this in mind
if it's ever exposed for bulk export rather than display (see frontend csvExport.ts,
which strips any `source: 'tiingo'` CSV column once more than one bank's row is
being exported).
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


def total_return_pct(bars_asc: list[dict]) -> float | None:
    """Simple total return over the given bars' adjusted close, first bar to last,
    as a percentage. None if fewer than 2 priced bars."""
    closes = [b["adj_close"] for b in bars_asc if b.get("adj_close") is not None]
    if len(closes) < 2 or not closes[0]:
        return None
    return round((closes[-1] - closes[0]) / closes[0] * 100, 2)


def max_drawdown_pct(bars_asc: list[dict]) -> float | None:
    """Largest peak-to-trough decline in adjusted close over the given bars, as a
    NEGATIVE percentage (e.g. -32.4 means a 32.4% drawdown from that bar's running
    peak). None if fewer than 2 priced bars."""
    closes = [b["adj_close"] for b in bars_asc if b.get("adj_close") is not None]
    if len(closes) < 2:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, (c - peak) / peak)
    return round(worst * 100, 2)


def rebased_series(bars_asc: list[dict], base: float = 100.0) -> list[dict]:
    """Adjusted-close series rebased so the FIRST bar in `bars_asc` equals `base` —
    for overlaying tickers with very different price levels on one relative-
    performance chart. `[{date, value}]`, oldest first. Empty if there's no priced
    first bar to rebase against."""
    priced = [(b["date"], b["adj_close"]) for b in bars_asc if b.get("adj_close") is not None]
    if not priced or not priced[0][1]:
        return []
    first = priced[0][1]
    return [{"date": d, "value": round(c / first * base, 4)} for d, c in priced]


def daily_return_series(bars_asc: list[dict]) -> dict[str, float]:
    """{date: simple daily return}, keyed by the LATER date of each consecutive
    pair — the same day-over-day change `daily_returns` computes, but keeping the
    calendar date so several tickers' return series can be joined on shared
    trading days (a correlation/beta input) rather than assumed to line up
    index-by-index, which breaks the moment two tickers have different history
    lengths or a gap (halt, late IPO, etc.)."""
    out: dict[str, float] = {}
    for i in range(1, len(bars_asc)):
        prev, cur = bars_asc[i - 1]["adj_close"], bars_asc[i]["adj_close"]
        if prev and cur and prev > 0:
            out[bars_asc[i]["date"]] = (cur - prev) / prev
    return out


def pearson_correlation(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Pearson correlation of two {date: return} series over their SHARED dates
    only. None if fewer than 10 shared trading days (too little overlap to mean
    anything) or either series has ~zero variance over that overlap."""
    shared = sorted(set(a) & set(b))
    if len(shared) < 10:
        return None
    xs, ys = [a[d] for d in shared], [b[d] for d in shared]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / math.sqrt(vx * vy), 4)


def beta_vs_benchmark(returns: dict[str, float], benchmark_returns: dict[str, float]) -> float | None:
    """OLS beta of `returns` against `benchmark_returns` (cov / benchmark variance)
    over their shared dates. None if fewer than 10 shared trading days or the
    benchmark has ~zero variance over that overlap."""
    shared = sorted(set(returns) & set(benchmark_returns))
    if len(shared) < 10:
        return None
    xs = [benchmark_returns[d] for d in shared]   # independent variable
    ys = [returns[d] for d in shared]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    if vx <= 0:
        return None
    return round(cov / vx, 4)


# ---- C10: does X-Ray severity predict forward returns? --------------------

_QUARTER_END = {"Q1": "0331", "Q2": "0630", "Q3": "0930", "Q4": "1231"}


def quarter_end_date(quarter: str) -> str | None:
    """"2026Q1" -> "2026-03-31". None if `quarter` isn't that shape. A stated
    simplification: uses the calendar quarter-end, not the (~30-45 day later)
    date a Call Report actually becomes public — this backtest does not model
    filing lag; see `forward_return_from`'s docstring."""
    if not quarter or len(quarter) != 6 or quarter[4] != "Q":
        return None
    y, q = quarter[:4], quarter[4:]
    md = _QUARTER_END.get(q)
    return f"{y}-{md[:2]}-{md[2:]}" if md else None


def forward_return_from(bars_asc: list[dict], from_date: str, horizon_days: int) -> float | None:
    """Simple return from the first bar ON OR AFTER `from_date` to the bar
    `horizon_days` TRADING days later. None if there's no bar on/after
    `from_date`, or fewer than `horizon_days` trading days remain after it —
    this never extrapolates or looks past the edge of what's actually landed.
    """
    idx = next((i for i, b in enumerate(bars_asc) if b["date"] >= from_date), None)
    if idx is None or idx + horizon_days >= len(bars_asc):
        return None
    start, end = bars_asc[idx]["adj_close"], bars_asc[idx + horizon_days]["adj_close"]
    if not start or not end:
        return None
    return round((end - start) / start * 100, 2)


def xray_severity_forward_returns(observations: list[dict]) -> dict:
    """C10 — the cheapest genuine validation available for the X-Ray rule
    engine: do banks it flags as high risk subsequently underperform?

    `observations`: `[{severity: 'low'|'elevated'|'high', forward_return_pct: float}]`
    — one row per (bank, historical quarter) where BOTH an X-Ray severity as
    of that quarter AND a subsequent landed price bar `horizon_days` later
    were available (see `forward_return_from`/`quarter_end_date` — callers
    build this list from real X-Ray evaluations against real Tiingo bars, no
    synthetic rows). Reports the mean forward return by severity bucket, the
    high-vs-low spread, and a Welch's-t-test-style z-score/p-value for that
    spread — NOT scipy (not a dependency here), a standard closed-form normal
    approximation, adequate at any sample size this feature will realistically
    see.  Published either way, per this feature's own instruction: a null
    result ("no detectable spread") is as reportable as a real one.
    """
    by_severity: dict[str, list[float]] = {"low": [], "elevated": [], "high": []}
    for o in observations:
        sev, r = o.get("severity"), o.get("forward_return_pct")
        if sev in by_severity and r is not None:
            by_severity[sev].append(r)

    def _stats(vals: list[float]) -> dict:
        n = len(vals)
        if n == 0:
            return {"n": 0, "mean": None, "stdev": None}
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
        return {"n": n, "mean": round(mean, 3), "stdev": round(var ** 0.5, 3)}

    summary = {sev: _stats(vals) for sev, vals in by_severity.items()}
    high, low = summary["high"], summary["low"]
    spread = z = p_value = None
    if high["n"] >= 2 and low["n"] >= 2:
        spread = round(high["mean"] - low["mean"], 3)
        se = ((high["stdev"] ** 2) / high["n"] + (low["stdev"] ** 2) / low["n"]) ** 0.5
        if se > 0:
            z = round(spread / se, 3)
            # Standard normal survival function via erf — two-sided p-value.
            p_value = round(math.erfc(abs(z) / math.sqrt(2)), 4)

    return {
        "by_severity": summary,
        "high_vs_low_spread_pp": spread,
        "z_score": z,
        "p_value": p_value,
        "significant_at_05": (p_value is not None and p_value < 0.05),
        "n_total": sum(s["n"] for s in summary.values()),
        "note": (
            "Positive high_vs_low_spread_pp means high-severity banks OUTPERFORMED "
            "low-severity ones going forward — the OPPOSITE of what the rule engine "
            "would want to see if it carries real signal. A null or positive result "
            "is a legitimate finding, not a failure of this analysis."
        ),
    }
