"""EBA EU-wide Transparency Exercise connector (Bronze).

Dataset: https://www.eba.europa.eu/eu-wide-transparency-exercise-0  (public
download, no auth, no API key — same "keyless, stdlib-only" discipline as
fdic.py). This is the EU's real analyst-grade bank-by-bank disclosure: ~120
significant EU/EEA banks' balance sheet, capital and P&L, published semi-annually
by the European Banking Authority.

Two real, live files back this connector (both verified by hand against the 2025
exercise — actual bytes fetched and inspected, not guessed from documentation):

  - ``TR_Metadata.xlsx``, sheet "List of Institutions": LEI -> bank name + country.
    A minimal stdlib-only .xlsx reader (``_read_institutions_sheet``) pulls just
    this one sheet — no openpyxl dependency, matching this repo's "Phase 1 is
    stdlib-only by design" convention (see pipelines/ingestion/pyproject.toml).
  - ``tr_oth.csv``: long format — one row per (bank, period, line-item). Assets,
    Liabilities, Capital, Leverage and P&L sheets are parsed here.

NOT parsed here, deliberately: ``tr_cre.csv`` (credit-risk/NPL cube — exposure
class x NACE sector x performing-status, needs the SDD.xlsx data dictionary to
decode correctly) and ``tr_sov.csv``/``tr_mrk.csv`` (sovereign/market risk). A
wrong NPL number from a misread multi-dimensional cube is worse than an honest
gap — see the "Next" section in this feature's docs once the mapping is verified.
This is real ceiling of EU bank granularity available today, not a shortcut: EBA
doesn't publish loan-category concentration or an uninsured-deposit split the way
FDIC's Call Reports do.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

from .base import Source

_ASSET_BASE = "https://www.eba.europa.eu/assets/TE2025/Full_database/883401"
INSTITUTIONS_URL = f"{_ASSET_BASE}/TR_Metadata.xlsx"
FINANCIALS_URL = f"{_ASSET_BASE}/tr_oth.csv"

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# tr_oth.csv Item codes -> our field names. Verified live against the 2025
# exercise's Assets/Liabilities/Capital/Leverage/P&L sheets (see this module's
# docstring). Ratios (CET1/Tier1/Total capital/leverage) are EBA's own reported
# "transitional period" figures.
FINANCIAL_ITEMS: dict[str, str] = {
    "2521001": "cash_and_balances",
    "2521010": "total_assets",
    "2521214": "total_liabilities",
    "2521216": "total_equity",
    "2520138": "total_risk_exposure_amount",   # RWA (transitional)
    "2520140": "cet1_ratio",
    "2520141": "tier1_rbc_ratio",
    "2520142": "total_rbc_ratio",
    "2520905": "leverage_ratio",
    "2520301": "interest_income",
    "2520304": "interest_expense",
    "2520309": "net_fee_income",
    "2520316": "total_operating_income",
    "2520335": "net_income",
}

# Verified live (2025 exercise): unlike FDIC's IDT1CER/RBCRWAJ/RBC1AAJ, which are
# already percentages (12.58 means 12.58%), EBA reports these four as raw
# fractions (0.1258 means 12.58%) — DekaBank's CET1 came back as 0.1841..., a
# fraction can't be a real CET1 ratio. Scaled to percent at fetch time so every
# downstream consumer of *_ratio fields (gold.py, xray.py) can treat FDIC- and
# EBA-sourced rows identically without a per-source special case.
_RATIO_FIELDS_NEED_PERCENT_SCALING = (
    "cet1_ratio", "tier1_rbc_ratio", "total_rbc_ratio", "leverage_ratio")

# Items dimensioned by IFRS 9 impairment stage (ASSETS_Stages = 1/2/3), which arrive
# as THREE rows per bank-period and MUST be summed to get the real total.
#
# Verified live before mapping, not assumed: Deutsche Bank's stage-3 slice of item
# 2521019 alone is EUR 14.1bn, which as a "total loan book" would be absurd for a
# EUR 1.4tn bank. Summing the stages gives EUR 614bn, which is plausible. A naive
# last-write-wins pivot silently keeps whichever stage the CSV happens to end on —
# exactly the multi-dimensional-cube trap this connector's docstring warns about for
# tr_cre.csv. Confirmed these 8 items vary on ASSETS_Stages ONLY (never on
# ASSETS_FV/Exposure/Financial_instruments), so a plain sum over stages is correct.
_STAGE_SUMMED_ITEMS: dict[str, str] = {
    "2521016": "securities_afs",            # FVOCI debt securities  (IFRS analogue of AFS)
    "2521018": "securities_htm",            # amortised-cost debt securities (analogue of HTM)
    "2521017": "loans_fvoci",
    "2521019": "loans_amortised_cost",
    "2521027": "allowance_loans_fvoci",     # accumulated impairment, FVOCI loans
    "2521029": "allowance_loans_amortised_cost",
}

# Stage 3 == "credit-impaired" under IFRS 9 — the closest real equivalent to FDIC's
# noncurrent-loans figure, and the only way EU banks get a genuine NPL ratio.
_STAGE3_ITEMS: dict[str, str] = {
    "2521017": "npl_loans_fvoci",
    "2521019": "npl_loans_amortised_cost",
}


class EbaSource(Source):
    """Fetch the EU-wide Transparency Exercise institution list + financials."""

    name = "eba.transparency"
    license = "eba-open"

    def __init__(self, *, timeout: float = 60.0, delay: float = 0.5,
                 max_retries: int = 4, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.user_agent = user_agent or "BankLens/0.1 (data pipeline; contact you@example.org)"

    # -- low-level -----------------------------------------------------------
    def _get_bytes(self, url: str) -> bytes:
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                time.sleep(self.delay)
                return body
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError) as err:
                last_err = err
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"EBA request failed after {self.max_retries} retries: {url}") from last_err

    # -- institutions (LEI -> name/country), stdlib-only .xlsx read ----------
    @staticmethod
    def _shared_strings(z: zipfile.ZipFile) -> list[str]:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        out = []
        for si in root.findall("m:si", _NS):
            texts = si.findall(".//m:t", _NS)
            out.append("".join(t.text or "" for t in texts))
        return out

    @classmethod
    def _read_institutions_sheet(cls, xlsx_bytes: bytes) -> list[dict]:
        """Parse "List of Institutions" (always sheet1.xml — first-listed sheet in
        every TR_Metadata.xlsx release) into {country, country_desc, lei, name}."""
        z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
        strings = cls._shared_strings(z)
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = sheet.findall(".//m:row", _NS)

        def cellval(c):
            v = c.find("m:v", _NS)
            if v is None or v.text is None:
                return None
            return strings[int(v.text)] if c.get("t") == "s" else v.text

        out = []
        for row in rows[1:]:                       # row 0 is the title merge, row 1 is headers
            vals = [cellval(c) for c in row.findall("m:c", _NS)]
            if len(vals) < 4 or not vals[2]:        # col C = LEI_Code
                continue
            if vals[0] == "Country":                # the header row itself
                continue
            out.append({"country": vals[0], "country_desc": vals[1],
                       "lei": vals[2], "name": vals[3]})
        return out

    def fetch_institutions(self) -> tuple[list[dict], str]:
        raw = self._get_bytes(INSTITUTIONS_URL)
        return self._read_institutions_sheet(raw), INSTITUTIONS_URL

    # -- financials (long-format CSV -> one row per bank per period) ---------
    @staticmethod
    def _pivot_financials_csv(text: str) -> list[dict]:
        """Every landed (LEI, Period) financial line-item we know how to read,
        pivoted wide: one dict per (LEI, Period) with our field names as keys.
        Unknown Item codes are silently skipped (not every one of ~150 codes in
        tr_oth.csv is mapped — see FINANCIAL_ITEMS for exactly which are). Pure
        function of the raw CSV text — no network — so it's unit-testable without
        a live fetch."""
        reader = csv.DictReader(io.StringIO(text))

        by_key: dict[tuple[str, str], dict] = defaultdict(dict)
        countries: dict[tuple[str, str], str] = {}
        for row in reader:
            item = row.get("Item")
            key = (row["LEI_Code"], row["Period"])
            try:
                value = float(row["Amount"])
            except (TypeError, ValueError):
                continue
            countries[key] = row.get("NSA")

            # 1) Scalar items: exactly one row per bank-period, assigned directly.
            field = FINANCIAL_ITEMS.get(item)
            if field is not None:
                if field in _RATIO_FIELDS_NEED_PERCENT_SCALING:
                    value *= 100
                if field in by_key[key]:
                    # A scalar item appearing twice means EBA added a dimension this
                    # item didn't previously carry. Assigning would silently keep one
                    # arbitrary slice and under-report the true figure, so fail loudly
                    # instead — a wrong balance sheet is worse than a failed landing.
                    raise ValueError(
                        f"EBA item {item} ({field}) appeared more than once for "
                        f"LEI={key[0]} period={key[1]} — it is now dimensioned and must "
                        f"move into _STAGE_SUMMED_ITEMS (or be handled explicitly) "
                        f"rather than assigned as a scalar.")
                by_key[key][field] = value
                continue

            # 2) Stage-dimensioned items: accumulate across IFRS 9 stages 1/2/3.
            summed = _STAGE_SUMMED_ITEMS.get(item)
            if summed is not None:
                by_key[key][summed] = by_key[key].get(summed, 0.0) + value
            stage3 = _STAGE3_ITEMS.get(item)
            if stage3 is not None and row.get("ASSETS_Stages") == "3":
                by_key[key][stage3] = by_key[key].get(stage3, 0.0) + value

        return [{"lei": lei, "period": period, "country": countries[(lei, period)], **fields}
               for (lei, period), fields in by_key.items()]

    def fetch_financials(self) -> tuple[list[dict], str]:
        raw = self._get_bytes(FINANCIALS_URL)
        text = raw.decode("utf-8", errors="replace")
        return self._pivot_financials_csv(text), FINANCIALS_URL

    def fetch(self) -> list[dict]:
        """`Source`'s required abstract method. `fetch_institutions`/`fetch_financials`
        above are the real entry points (two distinct endpoints, unlike FDIC's
        single-table fetch) — this just satisfies the base contract by returning
        the financials, the larger and more central of the two datasets."""
        rows, _ = self.fetch_financials()
        return rows
