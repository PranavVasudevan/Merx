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

import http.cookiejar
import json
import time
import urllib.parse
import urllib.request
import urllib.error

from .base import Source

API_ROOT = "https://banks.data.fdic.gov/api"

# Curated field set. Every code here is VERIFIED live against the FDIC API
# (probed, not guessed). See docs/domain/data-dictionary.md for the mapping and
# docs/data-contracts/bank_financials.silver.md for the contract.
FINANCIAL_FIELDS = [
    # identity + headline
    "CERT", "REPDTE", "NAMEFULL", "STALP", "ASSET",
    # deposits: total / domestic / insured / UNINSURED (reported) / core
    "DEP", "DEPDOM", "DEPINS", "DEPUNINS", "COREDEP",
    # loans & leases: gross / net
    "LNLSGR", "LNLSNET",
    # loan composition (RC-C schedule, $ thousands)
    "LNRE",        # total real estate loans
    "LNRECONS",    # construction & land development
    "LNREMULT",    # multifamily residential RE
    "LNRENRES",    # nonfarm nonresidential (CRE core)
    "LNRELOC",     # home-equity lines of credit
    "LNRERES",     # 1-4 family residential mortgages
    "LNREAG",      # farmland (agricultural RE)
    "LNAG",        # agricultural production loans
    "LNCI",        # commercial & industrial
    "LNCON",       # consumer loans (total)
    "LNCRCD",      # consumer: credit card
    "LNAUTO",      # consumer: auto
    "LNCONOTH",    # consumer: other
    # securities
    "SC",          # total securities
    "SCAF",        # available-for-sale (AFS), fair value
    "SCHA",        # held-to-maturity (HTM), amortized cost
    # capital & balance-sheet dollars (for the stress simulator, Feature 16)
    "EQ",          # total equity capital ($ thousands)
    "RBCT1J",      # Tier 1 capital ($)
    "RBC",         # Total risk-based capital ($)
    "RWAJT",       # risk-weighted assets ($)
    "ASSET5",      # average assets ($)
    "CHBAL",       # cash & balances due ($)
    # capital & performance RATIOS (already percentages — do NOT rescale)
    "IDT1CER",     # Common Equity Tier 1 (CET1) ratio
    "IDT1RWAJR",   # Tier 1 risk-based capital ratio
    "RBCRWAJ",     # Total risk-based capital ratio
    "RBC1AAJ",     # Tier 1 leverage ratio
    "EQV",         # equity / assets
    "LNLSDEPR",    # net loans / deposits (FDIC's own computation)
]

INSTITUTION_FIELDS = ["NAME", "CERT", "STALP", "CITY", "ACTIVE", "ASSET", "DEP", "ESTYMD"]


class FdicSource(Source):
    """Fetch institution profile + quarterly financials from FDIC BankFind."""

    name = "fdic.bankfind"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 30.0, delay: float = 0.4,
                 max_retries: int = 4, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay            # polite pause between calls
        self.max_retries = max_retries
        self.user_agent = user_agent or "BankLens/0.1 (data pipeline; contact you@example.org)"
        # A cookie-aware opener so the CDN/WAF's redirect+cookie challenge completes
        # (bare urllib can't, which surfaces as a 302 -> connection reset).
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    # -- low-level ---------------------------------------------------------
    def _get(self, endpoint: str, params: dict) -> tuple[dict, str]:
        """GET one endpoint, returning (parsed_json, final_url)."""
        query = urllib.parse.urlencode(params, safe=":,")
        url = f"{API_ROOT}/{endpoint}?{query}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",   # avoid gzip so .decode() is straightforward
            "Connection": "close",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                time.sleep(self.delay)  # be a good citizen
                return json.loads(body), url
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError) as err:
                last_err = err
                time.sleep(self.delay * (2 ** attempt))  # exponential backoff
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
