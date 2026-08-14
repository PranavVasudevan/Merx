"""FRED (Federal Reserve Economic Data) connector (Bronze).

Docs: https://fred.stlouisfed.org/docs/api/fred/ (public REST API; free key,
`FRED_API_KEY` — the ONE thing here that can't be verified without the user's
own key, same caveat sources/tiingo.py already carries for Tiingo).

docs/audit/04-remediation-prompts.md B5: land, at minimum, the Treasury yield
curve, Fed funds, unemployment, and a CRE price index — inputs the stress
engine (C4/C5, not in this pass) can eventually condition a scenario on
instead of an abstract bps slider.

IMPORTANT — unlike every other connector in this repo, the ``DEFAULT_SERIES``
IDs below were NOT live-verified against a real API response: this
environment had no working ``FRED_API_KEY`` (present in ``.env`` as an empty
placeholder) when this connector was written, so there was no key to probe
FRED with. The request/response SHAPE is real (FRED's REST contract is public
and stable — one JSON object with an ``observations`` list of
``{"date", "value"}`` pairs, "." for a missing observation), and the series
IDs below are the standard, long-established FRED identifiers for these
series, but the very first live run with a real key should be treated as the
verification step this repo's other connectors already got, not a rerun of
one that already passed. `fetch_series` itself is fully generic (works for
any FRED series id), so a wrong id here fails loudly (FRED returns a clear
JSON error) rather than landing wrong data silently.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import Source

API_ROOT = "https://api.stlouisfed.org/fred"

# Standard FRED series IDs — see this module's docstring for the "not live-
# verified in this session" caveat. Grouped by what B5 asks for.
DEFAULT_SERIES: dict[str, str] = {
    # Treasury yield curve (constant maturity, daily, percent)
    "treasury_3mo": "DGS3MO",
    "treasury_2yr": "DGS2",
    "treasury_5yr": "DGS5",
    "treasury_10yr": "DGS10",
    "treasury_30yr": "DGS30",
    # Fed funds — effective rate, daily
    "fed_funds": "DFF",
    # Unemployment rate — seasonally adjusted, monthly, percent
    "unemployment_rate": "UNRATE",
    # Commercial real estate price index — quarterly
    "cre_price_index": "COMREPUSQ159N",
}


class MissingApiKey(RuntimeError):
    pass


def get_api_key() -> str:
    key = os.environ.get("FRED_API_KEY") or _dotenv("FRED_API_KEY")
    if not key:
        raise MissingApiKey(
            "FRED_API_KEY not set. Get a free key (no card) at "
            "https://fred.stlouisfed.org/docs/api/api_key.html and add "
            "FRED_API_KEY=... to .env at the repo root (already git-ignored)."
        )
    return key


def _dotenv(key: str) -> str | None:
    """Same minimal .env reader every other client in this repo hand-rolls
    (see banklens_common.db._dotenv, anthropic_client.py) — no shared
    dependency, just consistency. Unlike sources/tiingo.py's get_api_key
    (env-var only), this also checks .env directly: TIINGO_API_KEY's own
    absence-handling was never exercised against a *populated* .env with an
    unset var, and FRED_API_KEY's real .env line IS exactly that case
    (present as a bare, commented-out placeholder) — worth handling correctly
    here even though it still resolves to MissingApiKey either way."""
    from pathlib import Path
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()   # strip inline comments
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


class FredSource(Source):
    """Fetch observations for a FRED series."""

    name = "fred"
    license = "public-domain-us-gov"

    def __init__(self, *, timeout: float = 30.0, delay: float = 0.3,
                 max_retries: int = 4, api_key: str | None = None) -> None:
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self._api_key = api_key

    def _get(self, params: dict) -> tuple[dict, str]:
        key = self._api_key or get_api_key()
        query = urllib.parse.urlencode({**params, "api_key": key, "file_type": "json"})
        url = f"{API_ROOT}/series/observations?{query}"
        headers = {"User-Agent": "BankLens/0.1 (data pipeline; contact you@example.org)",
                  "Accept": "application/json"}
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                time.sleep(self.delay)
                # A redacted URL (no key) for Provenance — FRED keys are free
                # and low-value, but there's no reason to ever persist one.
                safe_url = f"{API_ROOT}/series/observations?" + urllib.parse.urlencode(
                    {k: v for k, v in params.items()} | {"api_key": "REDACTED", "file_type": "json"})
                return body, safe_url
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"FRED API error {exc.code} for series "
                                  f"{params.get('series_id')}: {detail or exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_err = exc
                time.sleep(self.delay * (2 ** attempt))
        raise RuntimeError(f"FRED request failed after {self.max_retries} retries "
                           f"for series {params.get('series_id')}") from last_err

    def fetch_series(self, series_id: str, *, start_date: str | None = None,
                     end_date: str | None = None) -> tuple[list[dict], str]:
        """Every observation for one FRED series, as (rows, source_url).
        `date` YYYY-MM-DD, `value` float or None (FRED's own "." missing-value
        marker, converted here rather than left as a string a caller has to
        special-case)."""
        params: dict[str, str] = {"series_id": series_id}
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date
        payload, url = self._get(params)
        rows = [{"series_id": series_id, "date": o["date"],
                "value": None if o["value"] == "." else float(o["value"])}
               for o in payload.get("observations", [])]
        return rows, url

    def fetch(self, series_id: str, **kwargs) -> list[dict]:  # Source contract
        rows, _ = self.fetch_series(series_id, **kwargs)
        return rows
