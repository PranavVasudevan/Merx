"""FDIC Summary of Deposits (SOD) connector (Bronze) — real branch-level footprint.

Docs: https://banks.data.fdic.gov/docs/ (same API root as fdic.py; public, no auth).
Annual snapshot of every FDIC-insured branch: ~76,000 records/year across all US banks.

**A real data-quality issue, found live, drives this connector's field choice:**
`STALP`/`CITY`/`ADDRESS` are frozen at the bank's HEADQUARTERS for every branch record
for multiple banks checked (Citizens Bank: 984 branches, all reading "Providence, RI,
1 Citizens Plz" even though `SIMS_LATITUDE`/`SIMS_LONGITUDE` for those same records span
Florida to Washington state; Dime Community Bank: same pattern, 63 branches all reading
its HQ address). Only the geocoded coordinates are reliably branch-specific — see
docs/data-contracts/branch_footprint.md. This connector still lands STALP/CITY/ADDRESS
(useful for display, and some smaller banks' data may be fine) but
``banklens_transforms.footprint`` deliberately does NOT trust them for geographic
aggregation — it uses coordinates only.

Bulk pull, not per-bank: ~76k rows/year is far cheaper as ~8 paginated requests than
one request per bank (unlike Tiingo, FDIC's SOD endpoint has no documented low daily
cap, but pagination is still the right shape for a dataset this size).
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request

from .base import Source

API_ROOT = "https://banks.data.fdic.gov/api/sod"

# Verified live. STALP/CITY/ADDRESS are landed for completeness/display but NOT trusted
# for footprint aggregation (see module docstring) — SIMS_LATITUDE/SIMS_LONGITUDE are.
FIELDS = ["CERT", "YEAR", "STALP", "CITY", "ADDRESS", "ZIP",
          "SIMS_LATITUDE", "SIMS_LONGITUDE", "DEPSUMBR"]

_PAGE_SIZE = 10000


class SodSource(Source):
    """Fetch the full annual branch-level Summary of Deposits."""

    name = "fdic.sod"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 60.0, delay: float = 0.3,
                 max_retries: int = 3, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "BankLens/0.1 (research; +https://example.org/banklens; contact=you@example.org)"
        )
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _get_page(self, year: int, offset: int) -> tuple[list[dict], int]:
        fields = ",".join(FIELDS)
        url = (f"{API_ROOT}?filters=YEAR:{year}&fields={fields}"
              f"&limit={_PAGE_SIZE}&offset={offset}")
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                time.sleep(self.delay)
                rows = [r["data"] for r in body.get("data", [])]
                return rows, body.get("meta", {}).get("total", 0)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_err = exc
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"SOD request failed after {self.max_retries} retries: {url}") from last_err

    def fetch_all_branches(self, year: int) -> list[dict]:
        """Every FDIC-insured branch for `year` (paginated, ~8 requests for ~76k rows)."""
        all_rows: list[dict] = []
        offset = 0
        while True:
            rows, total = self._get_page(year, offset)
            all_rows.extend(rows)
            offset += _PAGE_SIZE
            if offset >= total or not rows:
                break
        return all_rows

    def fetch(self, year: int) -> list[dict]:  # Source contract
        return self.fetch_all_branches(year)
