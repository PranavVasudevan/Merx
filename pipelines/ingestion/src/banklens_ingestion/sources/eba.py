"""EBA EU-wide Transparency Exercise connector (Bronze).

Dataset: https://www.eba.europa.eu/eu-wide-transparency-exercise-0  (public
download, no auth, no API key — same "keyless, stdlib-only" discipline as
fdic.py). This is the EU's real analyst-grade bank-by-bank disclosure: ~120
significant EU/EEA banks' balance sheet, capital and P&L, published semi-annually
by the European Banking Authority.

Three real, live files back this connector (all verified by hand against the 2025
exercise — actual bytes fetched and inspected, not guessed from documentation):

  - ``TR_Metadata.xlsx``, sheet "List of Institutions": LEI -> bank name + country.
    A minimal stdlib-only .xlsx reader (``_read_institutions_sheet``) pulls just
    this one sheet — no openpyxl dependency, matching this repo's "Phase 1 is
    stdlib-only by design" convention (see pipelines/ingestion/pyproject.toml).
  - ``tr_oth.csv``: long format — one row per (bank, period, line-item). Assets,
    Liabilities, Capital, Leverage and P&L sheets are parsed here.
  - ``tr_cre.csv``: the credit-risk/NPL cube (exposure class x NACE sector x
    performing-status), 89 Item codes x every dimension combination. Only TWO
    Item codes are decoded here — see ``_pivot_credit_risk_csv`` — everything
    else in this cube is left unparsed.

The full ``tr_cre.csv`` cube is genuinely NOT decoded here: most of its Item
codes (exposure-class x SA/IRB x defaulted-status breakdowns) need dimension
dictionaries — an ``Exposure`` class-code table and a ``Country`` code table —
that neither ``SDD.xlsx`` nor the EBA's own "Mapped_templates" workbook publish
in a form this connector could verify byte-for-byte. Guessing those codes would
produce a wrong NPL/concentration number presented as real, which is worse than
an honest gap. ``tr_sov.csv``/``tr_mrk.csv`` (sovereign/market risk) are not
parsed at all, same reasoning.

The two Item codes that ARE decoded were verified two independent ways before
being trusted, not guessed from SDD.xlsx's item-label list alone:
  1. Arithmetically, on live 2025Q3 data: for Item 2520603, the sum of
     Perf_Status 1 ("performing") + Perf_Status 2 ("non-performing") equals
     Perf_Status 0 ("total") for every (LEI, Period) sampled — confirming the
     0/1/2 semantics without needing an external code table.
  2. Against the EBA's own "2025_EU-wide_Transparency_exercise_Mapped_templates"
     workbook, which lays out the same Item codes as human-readable template
     cells: the "NPE" sheet's row 17 is literally labelled "Loans and advances
     (including at amortised cost and fair value)" with columns "Gross carrying
     amount" (-> Perf_Status 0), "Of which performing" (-> 1) and "Of which
     non-performing" (-> 2); the "NACE" sheet's rows 11-29 list the 19 NACE
     Rev.2 sections A-S in that exact order, matching NACE_codes 1-19 in the CSV
     (row 30, "Loans and advances", is the NACE_codes=0 cross-sector total).

This is the real ceiling of EU bank credit-risk granularity available today, not
a shortcut: EBA doesn't publish US-style loan-category concentration (CRE vs
C&I vs consumer) or an uninsured-deposit split the way FDIC's Call Reports do.
"""

from __future__ import annotations

import csv
import http.cookiejar
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
CREDIT_RISK_URL = f"{_ASSET_BASE}/tr_cre.csv"

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

# tr_cre.csv Item codes decoded here — see this module's docstring for how each
# was verified. Every other Item code in the cube (89 total) is left alone.
_CREDIT_RISK_NPL_ITEM = "2520603"    # "Loans and advances" gross carrying amount
_CREDIT_RISK_NACE_ITEM = "2521301"   # "NACE | Gross carrying amount"

# Perf_Status dimension values, decoded for the two items above only (verified
# both arithmetically — Perf_Status 1 + Perf_Status 2 == Perf_Status 0 — and
# against the Mapped_templates workbook's own column headers; see docstring).
_PERF_TOTAL, _PERF_PERFORMING, _PERF_NONPERFORMING = "0", "1", "2"

# NACE Rev.2 section codes this cube uses, 1-19 (verified against the EBA's own
# "NACE" mapped-template sheet, rows 11-29 — see module docstring). NACE_codes
# "0" is the cross-sector total. The human-readable A-S section labels live in
# `banklens_transforms.silver_eba.NACE_SECTORS` (the Silver/decode layer, not
# ingestion) — this connector only needs to validate the raw code is in range.
_NACE_CODE_RANGE = range(1, 20)

# The dimension columns that must all read as the cross-bank AGGREGATE ("0")
# for a row to be the single-number total/NPL figure or a NACE sector slice —
# every OTHER combination of these five columns is a finer cut of the same cube
# (by exposure class, by counterparty country, by SA-vs-IRB approach, ...) that
# this connector does not attempt to decode. Confirmed live: for the sampled
# bank-period, summing NACE_codes 1-19 at this aggregate slice reproduces the
# NACE_codes=0 total exactly.
_AGGREGATE_DIMS = ("Portfolio", "Country", "Country_rank", "Exposure", "Status")


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
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    # -- low-level -----------------------------------------------------------
    def _get_bytes(self, url: str, *, timeout: float | None = None) -> bytes:
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                # Cookie-aware opener: some EBA assets (SDD.xlsx, the larger CSVs)
                # reset a bare urlopen connection without it, same WAF-cookie
                # discipline fdic.py already needs — see FdicSource._opener.
                with self._opener.open(req, timeout=timeout or self.timeout) as resp:
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
        # str | None, not str: an EBA row missing NSA (country) is a real,
        # disclosed gap -- this codebase's convention is to carry that as None
        # through to the caller, never fabricate a country to satisfy a
        # narrower type.
        countries: dict[tuple[str, str], str | None] = {}
        for row in reader:
            item = row.get("Item")
            if item is None:
                # Every FINANCIAL_ITEMS/_STAGE_SUMMED_ITEMS/_STAGE3_ITEMS
                # lookup below would just miss anyway (None matches nothing),
                # so this row was always silently skipped -- making that
                # explicit here instead of three separate no-op dict lookups.
                continue
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

    # -- credit risk (tr_cre.csv, two Item codes only) ------------------------
    @staticmethod
    def _pivot_credit_risk_csv(text: str) -> list[dict]:
        """``tr_cre.csv`` is a ~123MB, 89-Item-code cube most of which this
        connector does NOT decode (see module docstring). This pulls out only
        the two verified Item codes, at the cross-bank AGGREGATE dimension slice
        (every ``_AGGREGATE_DIMS`` column == "0"), and pivots to one dict per
        (LEI, Period):

          - NPL item (2520603): ``npl_gross_carrying_eur_m`` (Perf_Status total),
            ``npl_performing_eur_m`` (1), ``npl_nonperforming_eur_m`` (2).
          - NACE item (2521301): ``nace_gross_carrying_eur_m``, a
            ``{NACE_SECTORS key: amount}`` dict, one entry per sector actually
            present (NACE_codes 0, the cross-sector total, is not stored — it's
            recoverable as the sum of the per-sector values and storing it too
            would invite the two silently drifting apart on a future re-land).

        Pure function of the raw CSV text — no network — so it's unit-testable
        without a live 123MB fetch, same discipline as `_pivot_financials_csv`.
        """
        reader = csv.DictReader(io.StringIO(text))
        by_key: dict[tuple[str, str], dict] = defaultdict(dict)

        for row in reader:
            item = row.get("Item")
            if item not in (_CREDIT_RISK_NPL_ITEM, _CREDIT_RISK_NACE_ITEM):
                continue
            if any(row.get(d) != "0" for d in _AGGREGATE_DIMS):
                continue   # a finer cut of the cube (exposure class, country, ...) — skip
            try:
                value = float(row["Amount"])
            except (TypeError, ValueError):
                continue
            key = (row["LEI_Code"], row["Period"])
            perf = row.get("Perf_Status")

            if item == _CREDIT_RISK_NPL_ITEM:
                # perf (row.get("Perf_Status")) is Any | None -- a missing/
                # unrecognized value simply misses this dict (safe at
                # runtime, field stays None, the row below is skipped), same
                # as every other "not disclosed" gap this connector handles.
                field = {_PERF_TOTAL: "npl_gross_carrying_eur_m",
                        _PERF_PERFORMING: "npl_performing_eur_m",
                        _PERF_NONPERFORMING: "npl_nonperforming_eur_m"}.get(perf)  # type: ignore[arg-type]
                if field is not None:
                    by_key[key][field] = value
            elif item == _CREDIT_RISK_NACE_ITEM and perf == _PERF_TOTAL:
                nace_code = row.get("NACE_codes")
                if nace_code and int(nace_code) in _NACE_CODE_RANGE:
                    sectors = by_key[key].setdefault("nace_gross_carrying_eur_m", {})
                    sectors[nace_code] = value

        return [{"lei": lei, "period": period, **fields}
               for (lei, period), fields in by_key.items()]

    def fetch_credit_risk(self) -> tuple[list[dict], str]:
        """Fetch + pivot ``tr_cre.csv``. ~123MB over the wire (the full cube, not
        yet filtered — filtering happens client-side in `_pivot_credit_risk_csv`
        so what's landed to Bronze is the narrow, decoded result, the same
        "curate at fetch time" discipline `fetch_financials` already applies to
        `tr_oth.csv`'s ~150 Item codes)."""
        raw = self._get_bytes(CREDIT_RISK_URL, timeout=max(self.timeout, 180.0))
        text = raw.decode("utf-8", errors="replace")
        return self._pivot_credit_risk_csv(text), CREDIT_RISK_URL

    def fetch(self) -> list[dict]:
        """`Source`'s required abstract method. `fetch_institutions`/`fetch_financials`
        above are the real entry points (two distinct endpoints, unlike FDIC's
        single-table fetch) — this just satisfies the base contract by returning
        the financials, the larger and more central of the two datasets."""
        rows, _ = self.fetch_financials()
        return rows
