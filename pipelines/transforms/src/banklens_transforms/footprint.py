"""Branch-level geographic footprint (Feature 15's geo-overlap, and the basis for
deposit-market concentration).

**Correction to an earlier finding.** This module used to bin branch coordinates into
a 0.4-degree grid and documented that as necessary, because FDIC's SOD `STALP`/`CITY`/
`ADDRESS` are frozen at the bank's HEADQUARTERS on every branch row. The freeze is
real — but those are the *institution-level* fields. FDIC also serves *branch-level*
fields, and they are correct and complete. Re-probed live against the same banks that
were originally cited as evidence:

    Citizens Bank NA   984 branches -> 16 states, 140 counties, 0 null
    Wells Fargo      4,214 branches -> 40 states, 787 counties, 0 null
    JPMorgan         4,993 branches -> 49 states, 611 counties, 0 null

So the original conclusion was wrong: it was a field-selection bug, not a source
defect. Aggregation now keys on `STCNTYBR` (FIPS state+county), which is the market
definition the **Federal Reserve and DOJ actually use** for deposit-concentration and
merger review — so an HHI computed on it means something, where an HHI on invented
grid squares would not.

The coordinate grid is kept as a **fallback** for rows with no county code (and it is
still what the synthetic unit tests exercise). `cell_overlap` and
`deposit_weighted_overlap` keep their exact signatures and semantics, so
`ma_fit.geo_overlap` is unchanged — its inputs simply became real markets. Each
footprint reports `geo_basis` ("county" or "grid") so a consumer can tell which it got.
"""

from __future__ import annotations

from collections import defaultdict

CELL_SIZE_DEG = 0.4


def grid_cell(lat: float, lon: float, cell_size: float = CELL_SIZE_DEG) -> tuple[int, int]:
    """Coordinate fallback bucket, ~27-30 miles. Used only when a branch row carries
    no FIPS county code."""
    return (round(lat / cell_size), round(lon / cell_size))


def county_key(record: dict) -> str | None:
    """FIPS state+county for a branch row, zero-padded to the canonical 5 digits.

    FDIC returns STCNTYBR as an integer, so leading zeros are lost — 6073 (San Diego)
    must become "06073" or it collides in string space with 60730 and sorts wrongly.
    """
    raw = record.get("STCNTYBR")
    if raw in (None, ""):
        return None
    try:
        return f"{int(raw):05d}"
    except (TypeError, ValueError):
        return None


def _branch_deposits_usd(record: dict) -> float:
    # DEPSUMBR is $ thousands, matching FDIC's convention everywhere else.
    return (record.get("DEPSUMBR") or 0) * 1000


def build_footprints(branch_records: list[dict]) -> dict[int, dict]:
    """One pass over the landed SOD dataset -> {cert: footprint} for every bank.

    A footprint: {cert, branch_count, cells (set), deposits_by_cell, total_deposits,
    centroid, geo_basis, counties, states}. Branches missing both a county code and
    coordinates are counted in `branch_count` but excluded from `cells` — they can't
    be placed, and silently dropping them from the count would misstate network size.
    """
    by_cert: dict[int, list[dict]] = defaultdict(list)
    for r in branch_records:
        cert = r.get("CERT")
        if cert is not None:
            by_cert[int(cert)].append(r)

    footprints: dict[int, dict] = {}
    for cert, branches in by_cert.items():
        cells: set = set()
        deposits_by_cell: dict = defaultdict(float)
        counties: set[str] = set()
        states: set[str] = set()
        lats, lons, total_dep = [], [], 0.0
        used_county = False

        for b in branches:
            dep = _branch_deposits_usd(b)
            total_dep += dep

            fips = county_key(b)
            if fips:
                counties.add(fips)
                used_county = True
            st = b.get("STALPBR")
            if st:
                states.add(st)

            lat, lon = b.get("SIMS_LATITUDE"), b.get("SIMS_LONGITUDE")
            # Prefer the real administrative market; fall back to the coordinate grid.
            cell = fips if fips else (
                grid_cell(float(lat), float(lon)) if lat is not None and lon is not None else None)
            if cell is not None:
                cells.add(cell)
                deposits_by_cell[cell] += dep
            if lat is not None and lon is not None:
                lats.append(float(lat)); lons.append(float(lon))

        centroid = (sum(lats) / len(lats), sum(lons) / len(lons)) if lats else None
        footprints[cert] = {
            "cert": cert, "branch_count": len(branches), "cells": cells,
            "deposits_by_cell": dict(deposits_by_cell), "total_deposits": total_dep,
            "centroid": centroid, "geo_basis": "county" if used_county else "grid",
            "counties": counties, "states": states,
        }
    return footprints


def cell_overlap(fp_a: dict | None, fp_b: dict | None) -> float | None:
    """Jaccard overlap of the two branch networks' markets (None if either unknown)."""
    if not fp_a or not fp_b:
        return None
    a, b = fp_a.get("cells") or set(), fp_b.get("cells") or set()
    if not a or not b:
        return None
    inter = a & b
    union = a | b
    return round(len(inter) / len(union), 4) if union else 0.0


def deposit_weighted_overlap(fp_a: dict | None, fp_b: dict | None) -> float | None:
    """A richer, secondary signal: overlap weighted by branch DEPOSITS in shared
    markets, not just market counts — two banks sharing one huge-deposit market matters
    more than sharing one small branch's. Intersection-over-union on market deposits."""
    if not fp_a or not fp_b:
        return None
    da, db = fp_a.get("deposits_by_cell") or {}, fp_b.get("deposits_by_cell") or {}
    if not da or not db:
        return None
    shared = set(da) & set(db)
    inter = sum(min(da[c], db[c]) for c in shared)
    union = sum(da.values()) + sum(db.values()) - sum(min(da.get(c, 0), db.get(c, 0)) for c in shared)
    return round(inter / union, 4) if union > 0 else 0.0


def county_deposit_table(branch_records: list[dict]) -> dict[str, dict]:
    """{fips: {fips, name, state, total_deposits, by_cert: {cert: $}, branch_count}}.

    The input to deposit-market concentration (HHI). Built over the FULL landed SOD —
    every FDIC-insured bank, not just the $1B-$250B analytical slice — because a market
    share computed against a partial denominator is simply wrong, and would overstate
    every share in the slice.
    """
    out: dict[str, dict] = {}
    for r in branch_records:
        fips = county_key(r)
        cert = r.get("CERT")
        if fips is None or cert is None:
            continue
        entry = out.get(fips)
        if entry is None:
            entry = out[fips] = {
                "fips": fips, "name": r.get("CNTYNAMB"), "state": r.get("STALPBR"),
                "total_deposits": 0.0, "by_cert": defaultdict(float), "branch_count": 0,
            }
        dep = _branch_deposits_usd(r)
        entry["total_deposits"] += dep
        entry["by_cert"][int(cert)] += dep
        entry["branch_count"] += 1
    for entry in out.values():
        entry["by_cert"] = dict(entry["by_cert"])
    return out


def herfindahl(shares_pct: list[float]) -> float:
    """HHI = sum of squared market shares expressed in percentage points (0-10,000).

    This is the Department of Justice / Federal Reserve convention used in the Bank
    Merger Competitive Review guidelines, NOT the 0-1 normalized variant — so the
    published screening thresholds (1,800 concentrated; +200 change) apply directly.
    """
    return round(sum(s * s for s in shares_pct), 1)


def county_concentration(entry: dict) -> dict:
    """HHI + ranked bank shares for one county, from a `county_deposit_table` entry."""
    total = entry.get("total_deposits") or 0.0
    if total <= 0:
        return {**{k: entry.get(k) for k in ("fips", "name", "state", "branch_count")},
                "total_deposits": total, "hhi": None, "shares": []}
    shares = [{"cert": c, "deposits": d, "share_pct": round(d / total * 100, 4)}
              for c, d in entry["by_cert"].items()]
    shares.sort(key=lambda s: s["deposits"], reverse=True)
    return {
        "fips": entry["fips"], "name": entry.get("name"), "state": entry.get("state"),
        "branch_count": entry.get("branch_count", 0), "total_deposits": total,
        "hhi": herfindahl([s["share_pct"] for s in shares]),
        "shares": shares,
    }
