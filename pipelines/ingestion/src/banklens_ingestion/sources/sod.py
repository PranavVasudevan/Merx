"""FDIC Summary of Deposits (SOD) connector (Bronze) — real branch-level footprint.

Docs: https://banks.data.fdic.gov/docs/ (same API root as fdic.py; public, no auth).
Annual snapshot of every FDIC-insured branch: ~76,000 records/year across all US banks.

**Correction to a previously-documented "FDIC data-quality bug".** This connector, and
``banklens_transforms.footprint``, used to state that FDIC's SOD had no usable branch
geography — that `STALP`/`CITY`/`ADDRESS` are frozen at the bank's HEADQUARTERS for
every branch record. The freeze is real, but the conclusion was wrong: those are the
*institution-level* fields. The API also serves *branch-level* fields, and they are
correct and complete. Re-probed live against the exact banks cited as evidence:

    bank                branches  institution STALP  branch STALPBR  counties  null
    Citizens Bank NA         984                  1              16       140     0
    Wells Fargo            4,214                  1              40       787     0
    JPMorgan               4,993                  1              49       611     0
    Dime Community            63                  1               1         8     0

So this was a field-selection bug, not a source defect. Landing `STCNTYBR` (FIPS
state+county) means geographic aggregation can use **real counties** — which is the
market definition the Federal Reserve and DOJ actually use for deposit-concentration
and merger review — instead of binning coordinates into an invented grid.

Institution-level STALP/CITY/ADDRESS are still landed for display, clearly distinct
from the BR-suffixed branch fields.

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

# Every code verified live against the API (probed, not guessed). The BR-suffixed
# fields are BRANCH-level and are the ones footprint aggregation trusts; the bare
# STALP/CITY/ADDRESS are INSTITUTION-level (HQ, identical on every row of a bank) and
# are landed for display only. See the module docstring for the measured proof.
FIELDS = [
    "CERT", "YEAR",
    # institution-level (HQ — do not aggregate on these)
    "STALP", "CITY", "ADDRESS", "ZIP",
    # branch-level identity + geography
    "BRNUM",       # branch number within the bank
    "NAMEBR",      # branch name
    "STALPBR",     # branch state
    "CITYBR",      # branch city
    "ZIPBR",       # branch ZIP
    "STCNTYBR",    # branch FIPS state+county code — the Fed/DOJ market unit
    "CNTYNAMB",    # branch county name
    "MSABR",       # branch metropolitan statistical area
    # geocode + money
    "SIMS_LATITUDE", "SIMS_LONGITUDE",
    "DEPSUMBR",    # deposits at this branch ($ thousands)
]

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

    def page_url(self, year: int, offset: int) -> str:
        return (f"{API_ROOT}?filters=YEAR:{year}&fields={','.join(FIELDS)}"
                f"&limit={_PAGE_SIZE}&offset={offset}")

    def _get_page(self, year: int, offset: int) -> tuple[list[dict], int]:
        url = self.page_url(year, offset)
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
