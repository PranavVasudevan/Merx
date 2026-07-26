"""CERT <-> CIK <-> RSSD identity crosswalk.

The join key that unifies FDIC (bank-level, CERT), the Fed (holding-company, RSSD),
and SEC EDGAR (public filer, CIK). SEC filers are almost always the PUBLIC HOLDING
COMPANY, not the bank subsidiary — so this matches on FDIC's ``NAMEHCR`` (holding
company name) against SEC's filer titles, not the bank's own name.

Dependency-free fuzzy matching via stdlib ``difflib`` (no fuzzywuzzy/rapidfuzz).
Exact-normalized matches are near-free; the fuzzy fallback only runs for the (much
smaller) remainder, which keeps this fast enough for the ~1,000-bank MVP slice.
"""

from __future__ import annotations

import difflib
import re

# Corporate-suffix / banking-industry / SEC-appended noise stripped before comparison.
# Banking words (BANK, TRUST, BANCORP...) are stripped on BOTH sides symmetrically —
# without this, "X Bancorp" vs "X Bank, National Association" (the same real company,
# renamed when a holding company merges into its bank subsidiary) scores far lower
# than it should, since one side loses "Bancorp" but the other keeps "Bank".
_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LLC|L L C|"
    r"NATIONAL ASSOCIATION|N A|NA|HOLDING|HOLDINGS|GROUP|BANCORP|BANCORPORATION|"
    r"BANCSHARES|FINANCIAL SERVICES|FINANCIAL|BANK|BANKSHARES|TRUST|SAVINGS)\b\.?",
)
_STATE_SUFFIX = re.compile(r"/[A-Z]{2}/?$")   # SEC appends e.g. "/MN", "/UT/"
_PUNCT = re.compile(r"[.,&/\\'\"]")


def normalize_name(name: str | None) -> str:
    """Uppercase, strip corporate suffixes/punctuation, collapse whitespace."""
    if not name:
        return ""
    s = name.upper()
    s = _STATE_SUFFIX.sub("", s)
    s = _PUNCT.sub(" ", s)
    s = _SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def first_token(normalized_name: str) -> str:
    """The first word of a normalized name — almost always the actual distinguishing
    brand/proper noun (DIME, WELLS, ZIONS), since generic banking words (COMMUNITY,
    TRUST, BANCORP, FINANCIAL) were already stripped from the middle/end by
    ``normalize_name``. Used to BLOCK candidates before fuzzy scoring: two companies
    that don't even share their first token are not the same company, no matter how
    similar their remaining words look."""
    return normalized_name.split(" ", 1)[0] if normalized_name else ""


#: Confidence tiers. "low_confidence" matches are surfaced, not dropped — a human
#: (or a future proper crosswalk source, e.g. the Fed NIC / academic CIK-RSSD link
#: tables) should confirm them rather than trust fuzzy string matching blindly.
HIGH_CONFIDENCE = 0.85
LOW_CONFIDENCE = 0.60


def build_crosswalk(
    holding_companies: dict[int, str],     # rssd -> holding-company name (from FDIC)
    sec_tickers: dict[int, dict],          # cik -> {"ticker", "title"} (from SEC)
) -> list[dict]:
    """Match each FDIC holding company to its most likely SEC filer.

    Always returns the single best candidate found (if any), tagged with a
    transparent confidence tier — never a silent binary match/no-match:
      "exact"           — identical after normalization
      "high_confidence" — fuzzy score >= 0.85
      "low_confidence"  — fuzzy score in [0.60, 0.85) — needs review
      "none"            — no candidate SHARES A FIRST TOKEN with the target

    Candidates are BLOCKED by first token before fuzzy scoring (see ``first_token``):
    two names that don't even share their leading word are never compared, which is
    what stops e.g. "DIME COMMUNITY BANCSHARES" from fuzzy-matching an unrelated
    "COMMUNITY TRUST BANCORP" just because they share the generic word "COMMUNITY".
    """
    # Pre-normalize the SEC side once, bucketed by first token for blocking.
    sec_norm: dict[str, list[int]] = {}
    sec_by_token: dict[str, list[str]] = {}
    for cik, info in sec_tickers.items():
        n = normalize_name(info["title"])
        if n not in sec_norm:
            sec_by_token.setdefault(first_token(n), []).append(n)
        sec_norm.setdefault(n, []).append(cik)

    out = []
    for rssd, hc_name in holding_companies.items():
        norm = normalize_name(hc_name)
        row = {"rssd": rssd, "name": hc_name, "cik": None, "ticker": None,
              "sec_title": None, "match_score": 0.0, "match_type": "none"}
        if not norm:
            out.append(row)
            continue

        if norm in sec_norm:
            cik = sec_norm[norm][0]
            info = sec_tickers[cik]
            row.update(cik=cik, ticker=info["ticker"], sec_title=info["title"],
                      match_score=1.0, match_type="exact")
            out.append(row)
            continue

        bucket = sec_by_token.get(first_token(norm), [])
        candidates = difflib.get_close_matches(norm, bucket, n=1, cutoff=LOW_CONFIDENCE)
        if candidates:
            best = candidates[0]
            score = round(match_score(norm, best), 4)
            cik = sec_norm[best][0]
            info = sec_tickers[cik]
            tier = "high_confidence" if score >= HIGH_CONFIDENCE else "low_confidence"
            row.update(cik=cik, ticker=info["ticker"], sec_title=info["title"],
                      match_score=score, match_type=tier)
        out.append(row)
    return out


def crosswalk_stats(rows: list[dict]) -> dict:
    tiers = {"exact": 0, "high_confidence": 0, "low_confidence": 0, "none": 0}
    for r in rows:
        tiers[r["match_type"]] += 1
    matched = tiers["exact"] + tiers["high_confidence"] + tiers["low_confidence"]
    return {"total": len(rows), **tiers,
            "match_rate_pct": round(matched / len(rows) * 100, 1) if rows else 0.0}
