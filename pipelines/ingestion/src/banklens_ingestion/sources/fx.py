"""EUR->USD reference rate (Bronze) — the one thing standing between "EBA reports
in EUR, FDIC reports in USD" and every downstream percentile/leaderboard/compare
silently treating a German bank's EUR total_assets as if it were USD.

Uses Frankfurter (https://frankfurter.dev), a free keyless wrapper around the
European Central Bank's own published daily reference rates — same public-data
provenance discipline as every other connector here, just proxied through a
convenience API instead of scraping ECB's XML feed directly. Real, live, no key.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import Source

API_URL = "https://api.frankfurter.dev/v1/latest?from=EUR&to=USD"


class FxSource(Source):
    """Fetch today's ECB EUR->USD reference rate."""

    name = "ecb.fx"
    license = "eba-open"   # ECB reference rates: free reuse, same posture as EBA's own data

    def __init__(self, *, timeout: float = 15.0, max_retries: int = 3,
                 user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent or "BankLens/0.1 (data pipeline; contact you@example.org)"

    def fetch_eur_usd(self) -> dict:
        """{"rate": 1.1554, "date": "2026-08-05", "source_url": API_URL} — the rate
        and its as-of date are landed alongside every EUR-denominated Silver row
        that used it, so a conversion is always traceable, not just applied."""
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(API_URL, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                return {"rate": payload["rates"]["USD"], "date": payload["date"],
                       "source_url": API_URL}
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError, KeyError) as err:
                last_err = err
                time.sleep(1.5 * attempt)
        raise RuntimeError(f"EUR->USD rate fetch failed after {self.max_retries} retries") from last_err

    def fetch(self) -> list[dict]:
        return [self.fetch_eur_usd()]
