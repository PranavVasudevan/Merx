"""Branch-level geographic footprint (Feature 15's real geo-overlap upgrade).

**Why grid cells instead of states/counties** — a real data-quality finding, not a
design preference: FDIC's own SOD `STALP`/`CITY`/`ADDRESS` fields are frozen at the
bank's HEADQUARTERS address for every branch record, for every multi-branch bank
checked live (Citizens Bank: 984 branches, all reading "Providence, RI"; Dime
Community Bank: 63 branches, all reading its Hauppauge HQ). Only
`SIMS_LATITUDE`/`SIMS_LONGITUDE` are reliably branch-specific (verified: those same
Citizens Bank records span lat 25.75-44.89, lon -122.5 to -69.99 — genuinely
nationwide, while the "city" field never changes). Building a footprint from the
state/city fields would silently launder bad data into a confident-looking result.
So: bin the one reliable field — real coordinates — into a coarse geographic grid,
and measure overlap on that. This also arguably better answers the actual M&A
question ("do these branch networks physically overlap") than administrative state
boundaries do anyway.

Cell size: 0.4 degrees ≈ 27-30 miles (shrinking slightly with latitude for longitude)
— a rough "local market" scale. This is intentionally coarse; it is not survey-grade
geocoding, and error is expected to concentrate at cell edges.
"""

from __future__ import annotations

from collections import defaultdict

CELL_SIZE_DEG = 0.4


def grid_cell(lat: float, lon: float, cell_size: float = CELL_SIZE_DEG) -> tuple[int, int]:
    return (round(lat / cell_size), round(lon / cell_size))


def build_footprints(branch_records: list[dict]) -> dict[int, dict]:
    """One pass over the full landed SOD dataset -> {cert: footprint} for every bank.

    A footprint: {cert, branch_count, cells (set), deposits_by_cell (dict cell->$),
    total_deposits, centroid (lat, lon)}. Branches missing coordinates are counted
    but excluded from the cell set (can't place them reliably).
    """
    by_cert: dict[int, list[dict]] = defaultdict(list)
    for r in branch_records:
        cert = r.get("CERT")
        if cert is not None:
            by_cert[int(cert)].append(r)

    footprints: dict[int, dict] = {}
    for cert, branches in by_cert.items():
        cells: set[tuple[int, int]] = set()
        deposits_by_cell: dict[tuple[int, int], float] = defaultdict(float)
        lats, lons, total_dep = [], [], 0.0
        for b in branches:
            lat, lon = b.get("SIMS_LATITUDE"), b.get("SIMS_LONGITUDE")
            dep = (b.get("DEPSUMBR") or 0) * 1000  # thousands -> USD, matching FDIC convention
            total_dep += dep
            if lat is not None and lon is not None:
                cell = grid_cell(float(lat), float(lon))
                cells.add(cell)
                deposits_by_cell[cell] += dep
                lats.append(float(lat)); lons.append(float(lon))
        centroid = (sum(lats) / len(lats), sum(lons) / len(lons)) if lats else None
        footprints[cert] = {
            "cert": cert, "branch_count": len(branches), "cells": cells,
            "deposits_by_cell": dict(deposits_by_cell), "total_deposits": total_dep,
            "centroid": centroid,
        }
    return footprints


def cell_overlap(fp_a: dict | None, fp_b: dict | None) -> float | None:
    """Jaccard overlap of branch-network grid cells (None if either footprint unknown)."""
    if not fp_a or not fp_b:
        return None
    a, b = fp_a.get("cells") or set(), fp_b.get("cells") or set()
    if not a or not b:
        return None
    inter = a & b
    union = a | b
    return round(len(inter) / len(union), 4) if union else 0.0


def deposit_weighted_overlap(fp_a: dict | None, fp_b: dict | None) -> float | None:
    """A richer, secondary signal: overlap weighted by branch DEPOSITS in shared cells,
    not just cell counts — two banks sharing one huge-deposit market matters more than
    sharing one small branch's cell. Intersection-over-union on cell deposit dollars."""
    if not fp_a or not fp_b:
        return None
    da, db = fp_a.get("deposits_by_cell") or {}, fp_b.get("deposits_by_cell") or {}
    if not da or not db:
        return None
    shared = set(da) & set(db)
    inter = sum(min(da[c], db[c]) for c in shared)
    union = sum(da.values()) + sum(db.values()) - sum(min(da.get(c, 0), db.get(c, 0)) for c in shared)
    return round(inter / union, 4) if union > 0 else 0.0
