"""Tiingo EOD price connector (Bronze) — the quant terminal's real candlestick data.

Docs: https://www.tiingo.com/documentation/end-of-day (verified live against Tiingo's
own docs pages, not guessed). Free tier: 250 calls/day, up to 50 symbols/hour, ~5
years of EOD history, no credit card. Get a free key at
https://api.tiingo.com/account/api/token — this is the one thing in this connector
that genuinely cannot be tested without the user's own key (unlike FDIC/SEC, which
are keyless); see docs/data-contracts/market_prices.md.

Auth: `Authorization: Token <key>` header (confirmed against Tiingo's connecting
docs — a `?token=` query param also works but the header keeps the key out of logs
and doesn't risk it landing in this connector's own provenance URL field).
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import Source

API_ROOT = "https://api.tiingo.com/tiingo/daily"

# Verified against Tiingo's own EOD docs page.
PRICE_FIELDS = ["date", "open", "high", "low", "close", "volume",
                "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume",
                "divCash", "splitFactor"]

# Free-tier discipline: 250 calls/day, 50 symbols/hour. This per-call delay only
# paces WITHIN one run (avoids hammering Tiingo back-to-back) — it does NOT by
# itself keep a batch under the 50/hour ceiling (2s x 50 = 100s, nowhere near an
# hour; a correction from an earlier version of this comment that overclaimed
# it did). The actual hourly ceiling is enforced statefully, across runs, by
# market_cli.py's persisted call log — see HOURLY_SYMBOL_CAP below and that
# module's _load_state/_calls_in_last_hour.
_MIN_DELAY_SECONDS = 2.0
HOURLY_SYMBOL_CAP = 50
DAILY_CALL_CAP = 250


class MissingApiKey(RuntimeError):
    pass


def get_api_key() -> str:
    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        raise MissingApiKey(
            "TIINGO_API_KEY not set. Get a free key (no card) at "
            "https://api.tiingo.com/account/api/token and add TIINGO_API_KEY=... "
            "to .env at the repo root (already git-ignored)."
        )
    return key


class TiingoSource(Source):
    """Fetch daily EOD OHLCV prices for a ticker."""

    name = "tiingo.eod"
    license = "commercial-licensed"  # NOT public-domain — see config/sources.yaml

    def __init__(self, *, timeout: float = 30.0, delay: float = _MIN_DELAY_SECONDS,
                 max_retries: int = 3, api_key: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self._api_key = api_key
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _get(self, url: str) -> object:
        key = self._api_key or get_api_key()
        headers = {"Content-Type": "application/json", "Authorization": f"Token {key}"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                time.sleep(self.delay)
                return json.loads(body)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(self.delay * (2 ** attempt))
                    last_err = exc
                    continue
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"Tiingo API error {exc.code}: {detail or exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"Tiingo request failed after {self.max_retries} retries: {url}") from last_err

    def fetch_daily_prices(self, ticker: str, start_date: str | None = None,
                           end_date: str | None = None) -> list[dict]:
        """Return raw EOD price rows for one ticker (newest last, per Tiingo's own order)."""
        params: dict[str, str] = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        qs = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{API_ROOT}/{ticker}/prices{qs}"
        rows = self._get(url)
        if not isinstance(rows, list):
            raise RuntimeError(f"Tiingo returned an unexpected shape for {ticker}: {rows}")
        for r in rows:
            r["_ticker"] = ticker
            r["_source_url"] = url
        return rows

    def fetch(self, ticker: str, **kwargs) -> list[dict]:  # Source contract
        return self.fetch_daily_prices(ticker, **kwargs)
