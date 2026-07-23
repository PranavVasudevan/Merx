"""FDIC BankFind Suite connector (Bronze).

Docs: https://banks.data.fdic.gov/docs/  (public REST API, no auth required)

Uses only the Python standard library so the Phase-1 vertical slice runs with
zero ``pip install``. Politeness is built in: an identifying User-Agent, a
per-request delay, and bounded retries with backoff — the same discipline the
production Rust connector will keep.

FDIC financial amounts are reported in **thousands of USD**; normalisation to
actual dollars happens later in the Silver layer, not here (Bronze stays raw).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import urllib.error

from .base import Source

API_ROOT = "https://banks.data.fdic.gov/api"

# Curated field set for the vertical slice. These codes are verified live against
# the FDIC API. The full Silver build widens this to loan-composition and capital
# fields; see docs/data-contracts/bank_financials.silver.md.
FINANCIAL_FIELDS = [
    "CERT", "REPDTE", "NAMEFULL", "STALP", "ASSET",
    "DEP", "DEPDOM", "DEPINS",          # deposits: total / domestic / insured
    "LNLSGR", "LNLSNET",                # loans & leases: gross / net
    "EQ",                                # total equity capital
]

INSTITUTION_FIELDS = ["NAME", "CERT", "STALP", "CITY", "ACTIVE", "ASSET", "DEP", "ESTYMD"]


class FdicSource(Source):
    """Fetch institution profile + quarterly financials from FDIC BankFind."""

    name = "fdic.bankfind"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 30.0, delay: float = 0.4,
                 max_retries: int = 3, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay            # polite pause between calls
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "BankLens/0.1 (research; +https://example.org/banklens; contact=you@example.org)"
        )

    # -- low-level ---------------------------------------------------------
    def _get(self, endpoint: str, params: dict) -> tuple[dict, str]:
        """GET one endpoint, returning (parsed_json, final_url)."""
        query = urllib.parse.urlencode(params, safe=":,")
        url = f"{API_ROOT}/{endpoint}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                time.sleep(self.delay)  # be a good citizen
                return json.loads(body), url
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
                last_err = err
                backoff = self.delay * (2 ** attempt)
                time.sleep(backoff)
        raise RuntimeError(f"FDIC request failed after {self.max_retries} retries: {url}") from last_err

    @staticmethod
    def _unwrap(payload: dict) -> list[dict]:
        """FDIC wraps each row as {"data": {...}, "score": ...}. Return the inner dicts."""
        return [row.get("data", {}) for row in payload.get("data", [])]

    # -- public ------------------------------------------------------------
    def get_institution(self, cert: int) -> dict:
        payload, url = self._get("institutions", {
            "filters": f"CERT:{cert}",
            "fields": ",".join(INSTITUTION_FIELDS),
            "limit": 1,
        })
        rows = self._unwrap(payload)
        if not rows:
            raise LookupError(f"No FDIC institution found for CERT {cert}")
        rows[0]["_source_url"] = url
        return rows[0]

    def search_institutions(self, name: str, limit: int = 10) -> list[dict]:
        payload, _ = self._get("institutions", {
            "filters": "ACTIVE:1",
            "search": f"NAME:{name}",
            "fields": ",".join(INSTITUTION_FIELDS),
            "sort_by": "ASSET", "sort_order": "DESC",
            "limit": limit,
        })
        return self._unwrap(payload)

    def fetch(self, cert: int, quarters: int = 8) -> list[dict]:
        """Return the most recent ``quarters`` financial records for a bank."""
        payload, url = self._get("financials", {
            "filters": f"CERT:{cert}",
            "fields": ",".join(FINANCIAL_FIELDS),
            "sort_by": "REPDTE", "sort_order": "DESC",
            "limit": quarters,
        })
        rows = self._unwrap(payload)
        for r in rows:
            r["_source_url"] = url
        return rows
