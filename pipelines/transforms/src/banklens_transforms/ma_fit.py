"""Feature 15 — M&A Fit Finder.

Given a target bank, ranks best-fit acquirers/partners from the peer population on:
  * funding complementarity  — a deposit-rich bank fills a loan-heavy bank's funding gap
  * business similarity       — cosine similarity of loan-mix (integration/strategic fit)
  * size compatibility        — a plausible acquirer is meaningfully larger than the target
  * geographic overlap        — REAL branch-footprint overlap (FDIC Summary of Deposits,
                                 grid-cell based — see banklens_transforms.footprint for why
                                 not states/counties: FDIC's own STALP/CITY fields are
                                 unreliable at branch level, verified live)

Output: a ranked candidate list with a short, human rationale per match. Pure functions
over Gold features + real branch footprints.
"""

from __future__ import annotations

import math

from .footprint import cell_overlap, deposit_weighted_overlap

# loan-mix vector used for business-similarity (cosine)
LOAN_MIX = [
    "concentration_ratio_cre", "concentration_ratio_c_and_i",
    "concentration_ratio_residential_mortgage", "concentration_ratio_consumer",
    "concentration_ratio_agricultural",
]

# balanced loan-to-deposit reference (~90%): below = deposit-rich, above = loan-heavy
_BALANCED_LTD = 90.0

DEFAULT_WEIGHTS = {"funding": 0.45, "business": 0.25, "size": 0.15, "geo": 0.15}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _funding_gap(bank: dict) -> float:
    ltd = bank.get("loan_to_deposit_pct")
    return (ltd if ltd is not None else _BALANCED_LTD) - _BALANCED_LTD


def funding_complementarity(target: dict, cand: dict) -> float:
    """1.0 when funding positions are strongly opposite (surplus meets deficit)."""
    gt = _clamp(_funding_gap(target) / 50.0, -1.0, 1.0)
    gc = _clamp(_funding_gap(cand) / 50.0, -1.0, 1.0)
    return round(0.5 - 0.5 * gt * gc, 4)     # opposite signs -> > 0.5


def _vec(bank: dict) -> list[float]:
    return [bank.get(k) or 0.0 for k in LOAN_MIX]


def business_similarity(target: dict, cand: dict) -> float:
    """Cosine similarity of loan-mix vectors (0..1)."""
    a, b = _vec(target), _vec(cand)
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return round(dot / (na * nb), 4) if na > 0 and nb > 0 else 0.0


def size_fit(target: dict, cand: dict) -> float:
    """Acquirer plausibility by assets: reward ~1.5x–6x the target."""
    t, c = target.get("total_assets"), cand.get("total_assets")
    if not t or not c:
        return 0.0
    ratio = c / t
    if ratio < 1.0:
        return round(0.2 * ratio, 4)          # smaller than target: unlikely acquirer
    if ratio < 1.5:
        return round(0.6 + (ratio - 1.0) * 0.8, 4)
    if ratio <= 6.0:
        return 1.0
    return round(max(0.2, 6.0 / ratio), 4)     # so large the target is a rounding error


def geo_overlap(target_fp: dict | None, cand_fp: dict | None) -> float | None:
    """Real branch-network overlap (grid-cell Jaccard; None if either footprint unknown).
    See banklens_transforms.footprint for why cells, not states/counties."""
    return cell_overlap(target_fp, cand_fp)


def _rationale(target, cand, comp, sim, szf, geo, shared_cells) -> str:
    bits = []
    tg, cg = _funding_gap(target), _funding_gap(cand)
    if comp > 0.6 and tg * cg < 0:
        rich, heavy = (cand, target) if cg < 0 else (target, cand)
        bits.append(f"{rich.get('name','partner')[:18].strip()} is deposit-rich, "
                    f"complementing the loan-heavy side")
    if sim >= 0.85:
        bits.append("very similar loan franchise (easy integration)")
    elif sim <= 0.5:
        bits.append("diversifying loan mix")
    ratio = (cand.get("total_assets") or 0) / (target.get("total_assets") or 1)
    bits.append(f"{ratio:.1f}x the target's size")
    if shared_cells:
        bits.append(f"branch networks overlap in {shared_cells} local market(s)")
    return "; ".join(bits)


def fit_score(target: dict, cand: dict, *, target_footprint: dict | None = None,
              cand_footprint: dict | None = None, weights=DEFAULT_WEIGHTS) -> dict:
    comp = funding_complementarity(target, cand)
    sim = business_similarity(target, cand)
    szf = size_fit(target, cand)
    geo = geo_overlap(target_footprint, cand_footprint)
    dep_geo = deposit_weighted_overlap(target_footprint, cand_footprint)

    w = dict(weights)
    if geo is None:                              # renormalize without geo
        gw = w.pop("geo")
        s = sum(w.values())
        w = {k: v / s * (s + gw) / s for k, v in w.items()} if s else w
        s2 = sum(w.values())
        w = {k: v / s2 for k, v in w.items()}
        score = comp * w["funding"] + sim * w["business"] + szf * w["size"]
    else:
        score = (comp * w["funding"] + sim * w["business"]
                 + szf * w["size"] + geo * w["geo"])

    shared_cells = 0
    if target_footprint and cand_footprint:
        shared_cells = len((target_footprint.get("cells") or set())
                           & (cand_footprint.get("cells") or set()))
    return {
        "cert_number": cand.get("cert_number"), "name": cand.get("name"),
        "fit_score": round(score, 4),
        "funding_complementarity": comp, "business_similarity": sim,
        "size_fit": szf, "geo_overlap": geo, "geo_overlap_deposit_weighted": dep_geo,
        "rationale": _rationale(target, cand, comp, sim, szf, geo, shared_cells),
    }


def rank_partners(target: dict, population: list[dict], *, top_n: int = 10,
                  footprints: dict | None = None) -> list[dict]:
    """Rank all other banks as acquirers/partners for the target."""
    t_fp = (footprints or {}).get(target.get("cert_number"))
    out = []
    for cand in population:
        if cand.get("cert_number") == target.get("cert_number"):
            continue
        c_fp = (footprints or {}).get(cand.get("cert_number"))
        out.append(fit_score(target, cand, target_footprint=t_fp, cand_footprint=c_fp))
    out.sort(key=lambda r: r["fit_score"], reverse=True)
    return out[:top_n]
