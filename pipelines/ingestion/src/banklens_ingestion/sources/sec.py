"""SEC EDGAR connector (Bronze).

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
No API key, but SEC REQUIRES an identifying User-Agent and caps requests at 10/s —
both enforced here (delay + explicit UA), same politeness discipline as the FDIC
connector.

Two endpoints:
  * company_tickers.json — bulk ticker/CIK/title list (all filers, ~1MB, one request)
  * companyfacts/CIK##########.json — a filer's full XBRL history (per-company)

Verified live: WELLS FARGO & COMPANY/MN = CIK 72971; its consolidated ``us-gaap:Assets``
for 2026-03-31 is $2.2055T (a holding-company superset of the ~$1.85T the FDIC reports
for the Wells Fargo Bank NA subsidiary alone — the expected relationship).
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request

from .base import Source

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


class SecSource(Source):
    """Fetch the ticker/CIK directory and per-company XBRL facts from SEC EDGAR."""

    name = "sec.edgar"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 30.0, delay: float = 0.15,
                 max_retries: int = 4, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay  # SEC caps at 10 req/s; 0.15s keeps us well under
        self.max_retries = max_retries
        self.user_agent = user_agent or "BankLens/0.1 (research; contact you@example.org)"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _get(self, url: str) -> dict:
        headers = {"User-Agent": self.user_agent, "Accept": "application/json",
                  "Accept-Encoding": "identity", "Connection": "close"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                time.sleep(self.delay)
                return json.loads(body)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError) as err:
                last_err = err
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"SEC request failed after {self.max_retries} retries: {url}") from last_err

    def fetch_company_tickers(self) -> dict[int, dict]:
        """Return {cik: {"ticker":..., "title":...}} for every SEC filer (dedup by CIK)."""
        raw = self._get(TICKERS_URL)
        out: dict[int, dict] = {}
        for row in raw.values():
            cik = int(row["cik_str"])
            out.setdefault(cik, {"ticker": row["ticker"], "title": row["title"]})
        return out

    def fetch_company_facts(self, cik: int) -> dict:
        """Return the raw XBRL companyfacts payload for one filer."""
        return self._get(FACTS_URL.format(cik=cik))

    def fetch(self, cik: int) -> list[dict]:  # Source contract
        return [self.fetch_company_facts(cik)]
