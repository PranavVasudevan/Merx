"""Federal Reserve NIC (National Information Center) connector (Bronze).

Docs: https://www.ffiec.gov/npw/FinancialReport/DataDownload and
.../FinancialDataDownload (public, no auth, no API key — same "keyless,
stdlib-only" discipline as fdic.py/eba.py). The Fed's own registry of bank
holding companies: who owns whom (``relationships``), what each holding
company is (``attributes``), and holding-company-level financials (FR Y-9C,
the ``financials``/BHCF files) — docs/audit/04-remediation-prompts.md B4.

Four real, live endpoints back this connector (all verified by hand — actual
bytes fetched and inspected via a browser network trace, not guessed from
documentation, since the NIC's own download PAGE is a JS-driven form with no
static links; the endpoints it calls are keyless GETs and stable regardless):

  - ``ReturnAttributesActiveZipFileCSV``: one row per ACTIVE entity in the
    Fed's registry (banks, holding companies, credit unions, ...) — RSSD ID,
    legal name, ``BHC_IND`` (1 = actually a bank holding company). This
    connector lands only the ``BHC_IND=1`` rows; the full registry is every
    supervised entity type, most of which BankLens has no use for.
  - ``ReturnRelationshipsZipFileCSV``: ownership edges (parent RSSD ->
    offspring RSSD, control indicator, percent equity, start/end date). Only
    OPEN relationships (``D_DT_END`` == "12/31/9999", i.e. not yet terminated)
    with ``CTRL_IND`` == 1 (a controlling stake, not just an equity position)
    are landed — that is the actual parent/subsidiary tree, not every
    historical or minority stake the Fed has ever recorded.
  - ``ReturnBHCFZipFiles?zipfilename=BHCF<YYYYMMDD>.ZIP``: one FR Y-9C
    financial-statement row per (RSSD, quarter), caret-delimited, ~2,200
    MDRM-coded columns. Only the curated ``FINANCIAL_FIELDS`` below are kept —
    decoded and verified against the Fed's own "Financial_Download_Dictionary"
    (at ``/npw/StaticData/DataDownload/Financial_Download_Dictionary.xlsx``)
    AND against a real filer's live numbers (JPMorgan Chase & Co, RSSD
    1039502, 2025Q4: BHCK2170 total assets $4.4249T, BHCKG105 total equity
    $362.614B, BHCAP793 CET1 ratio 14.5567% — all independently plausible).
    ``BHCA2170`` looks like the obvious "total assets" code from its
    description alone but is a DIFFERENT, mostly-unpopulated schedule variant
    for large filers (empty for JPMorgan) — a reminder that "which of several
    plausibly-named codes is actually populated" needs verifying against real
    data, not just the dictionary's descriptions. Land ONE quarter (the
    latest) by default; historical Y-9C backfill is real future work, not
    attempted here.

RSSD IDs are the join key everywhere in this connector, and to the rest of
BankLens: FDIC's own population records carry the bank's holding company's
RSSD as ``RSSDHCR`` (see sources/fdic.py's FINANCIAL_FIELDS), and
`banklens_transforms.crosswalk`'s rows are already keyed by ``rssd`` — so a
Fed NIC holding company joins to both the FDIC population AND the SEC/ticker
crosswalk on the exact same identifier, no fuzzy matching needed.
"""

from __future__ import annotations

import csv
import http.cookiejar
import io
import time
import urllib.error
import urllib.request
import zipfile

from .base import Source

_BASE = "https://www.ffiec.gov/npw/FinancialReport"
ATTRIBUTES_URL = f"{_BASE}/ReturnAttributesActiveZipFileCSV"
RELATIONSHIPS_URL = f"{_BASE}/ReturnRelationshipsZipFileCSV"


def financials_url(period: str) -> str:
    """`period`: YYYYMMDD quarter-end, e.g. "20251231"."""
    return f"{_BASE}/ReturnBHCFZipFiles?zipfilename=BHCF{period}.ZIP"


# Curated FR Y-9C headline fields (MDRM codes), verified live against a real
# filer (see module docstring). $ amounts are in THOUSANDS, matching FDIC's own
# convention; ratio fields are already percentages (14.5567 means 14.5567%),
# unlike EBA's raw-fraction convention.
FINANCIAL_FIELDS: dict[str, str] = {
    "BHCK2170": "total_assets",
    "BHCK2948": "total_liabilities",
    "BHCKG105": "total_equity_capital",
    "BHCAA223": "risk_weighted_assets",
    "BHCA8274": "tier1_capital",
    "BHCA3792": "total_capital",
    "BHCAP793": "cet1_ratio",
    "BHCA7206": "tier1_capital_ratio",
    "BHCA7205": "total_capital_ratio",
    "BHCA7204": "tier1_leverage_ratio",
    "BHCK4340": "net_income",
    "BHCK3163": "goodwill",
}

# Attributes CSV columns kept (of ~30) — RSSD ID/name/BHC flag/state, verified
# live against real rows. `NM_LGL` is padded with trailing spaces in the
# source (fixed-width legacy origin) — stripped at parse time.
_ATTRIBUTE_FIELDS = ("ID_RSSD", "NM_LGL", "NM_SHORT", "BHC_IND", "ORG_TYPE_CD")


class FedNicSource(Source):
    """Fetch Fed NIC holding-company attributes, ownership relationships and
    FR Y-9C financials."""

    name = "fed.nic"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 60.0, delay: float = 0.5,
                 max_retries: int = 6, user_agent: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.user_agent = user_agent or "BankLens/0.1 (data pipeline; contact you@example.org)"
        # Cookie-aware opener: this WAF resets a bare urlopen connection more
        # often than not (verified live, repeatedly) — same discipline
        # fdic.py/eba.py already need.
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def _get_bytes(self, url: str) -> bytes:
        headers = {
            "User-Agent": self.user_agent, "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "identity",
            "Connection": "close",
        }
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read()
                time.sleep(self.delay)
                return body
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ConnectionError) as err:
                last_err = err
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"Fed NIC request failed after {self.max_retries} retries: {url}") from last_err

    @staticmethod
    def _read_zip_csv(raw: bytes) -> list[dict]:
        """Every Fed NIC bulk download is a zip with exactly one member: a CSV
        whose header row starts with ``#`` (stripped here)."""
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8", errors="replace")
        if text.startswith("#"):
            text = text[1:]
        return list(csv.DictReader(io.StringIO(text)))

    def fetch_attributes(self) -> tuple[list[dict], str]:
        """Active bank holding companies only (``BHC_IND == "1"``) — the
        full registry (all supervised entity types) is landed and filtered
        client-side, matching the "curate at fetch time" discipline
        sources/eba.py's credit-risk cube uses."""
        raw = self._get_bytes(ATTRIBUTES_URL)
        rows = self._read_zip_csv(raw)
        out = [{f: r.get(f) for f in _ATTRIBUTE_FIELDS} for r in rows if r.get("BHC_IND") == "1"]
        for r in out:
            r["NM_LGL"] = (r.get("NM_LGL") or "").strip()
            r["NM_SHORT"] = (r.get("NM_SHORT") or "").strip()
            r["_source_url"] = ATTRIBUTES_URL
        return out, ATTRIBUTES_URL

    def fetch_relationships(self) -> tuple[list[dict], str]:
        """Open (``D_DT_END`` unset / far-future), controlling
        (``CTRL_IND == "1"``) ownership edges only — the real, current
        parent/subsidiary tree, not every historical or minority stake on
        record."""
        raw = self._get_bytes(RELATIONSHIPS_URL)
        rows = self._read_zip_csv(raw)
        out = [
            {"ID_RSSD_PARENT": r.get("ID_RSSD_PARENT"), "ID_RSSD_OFFSPRING": r.get("ID_RSSD_OFFSPRING"),
             "PCT_EQUITY": r.get("PCT_EQUITY"), "D_DT_START": r.get("D_DT_START"),
             "_source_url": RELATIONSHIPS_URL}
            for r in rows
            if r.get("CTRL_IND") == "1" and (r.get("D_DT_END") or "").startswith("12/31/9999")
        ]
        return out, RELATIONSHIPS_URL

    def fetch_financials(self, period: str) -> tuple[list[dict], str]:
        """`period`: YYYYMMDD quarter-end. Returns the curated
        ``FINANCIAL_FIELDS`` for every reporting holding company that quarter,
        keyed by RSSD ID."""
        url = financials_url(period)
        raw = self._get_bytes(url)
        z = zipfile.ZipFile(io.BytesIO(raw))
        name = z.namelist()[0]
        with z.open(name) as f:
            header = f.readline().decode("utf-8", errors="replace").strip().split("^")
            idx = {code: i for i, code in enumerate(header)}
            missing = [c for c in ("RSSD9001", "RSSD9999", *FINANCIAL_FIELDS) if c not in idx]
            if missing:
                raise RuntimeError(
                    f"Fed NIC BHCF{period} is missing expected column(s) {missing} — "
                    f"the bulk file's schema drifted; FINANCIAL_FIELDS needs re-verifying "
                    f"against Financial_Download_Dictionary.xlsx before this can be trusted.")
            out = []
            for line in f:
                vals = line.decode("utf-8", errors="replace").rstrip("\r\n").split("^")
                row = {"rssd": vals[idx["RSSD9001"]], "period": vals[idx["RSSD9999"]]}
                for code, field in FINANCIAL_FIELDS.items():
                    v = vals[idx[code]].strip()
                    row[field] = float(v) if v else None
                out.append(row)
        return out, url

    def fetch(self, period: str) -> list[dict]:  # Source contract
        rows, _ = self.fetch_financials(period)
        return rows
