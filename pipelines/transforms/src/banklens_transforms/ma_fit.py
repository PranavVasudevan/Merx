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

import bisect
import math
from collections import defaultdict

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
    dot = sum(x * y for x, y in zip(a, b, strict=True))
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
        w.pop("geo")
        s = sum(w.values())
        w = {k: v / s for k, v in w.items()} if s else w
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
    """Rank all other banks as acquirers/partners for the target — the exact,
    real O(n) sweep for ONE target. Fine for a single user-triggered lookup
    (find_ma_matches); network_edges() calling this for EVERY bank in the
    population is the real O(n^2) cost F8 addresses — see
    build_loan_mix_index()/rank_partners_approx() below."""
    t_fp = (footprints or {}).get(target.get("cert_number"))
    out = []
    for cand in population:
        if cand.get("cert_number") == target.get("cert_number"):
            continue
        c_fp = (footprints or {}).get(cand.get("cert_number"))
        out.append(fit_score(target, cand, target_footprint=t_fp, cand_footprint=c_fp))
    out.sort(key=lambda r: r["fit_score"], reverse=True)
    return out[:top_n]


# ---- F8: blocked/approximate nearest-neighbour search for the whole-network
#      view (network_edges()), where the naive approach scores EVERY bank
#      against EVERY other bank — the real O(n^2) cost measured live at ~17s
#      for the original 1,049-bank population, unworkable at B3's ~4,500-bank
#      universe. ---------------------------------------------------------

def _dominant_category(bank: dict) -> tuple[int, float]:
    """(index into LOAN_MIX of the bank's largest loan-mix share, that share)
    — a coarse signature used only to narrow the candidate set before exact
    fit_score(), not a replacement for business_similarity()'s real cosine
    computation."""
    vec = _vec(bank)
    idx = max(range(len(vec)), key=lambda i: vec[i])
    return idx, vec[idx]


def build_loan_mix_index(population: list[dict]) -> dict[int, list[tuple[float, dict]]]:
    """One pass over the population (O(n log n), the sort dominates): group
    banks by their DOMINANT loan-mix category, each group sorted by that
    category's share. `rank_partners_approx()` searches this index instead of
    scanning the whole population per target — build it ONCE and reuse it for
    every target, the same "build once" pattern the rest of Gold follows."""
    by_category: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    for bank in population:
        idx, share = _dominant_category(bank)
        by_category[idx].append((share, bank))
    for entries in by_category.values():
        entries.sort(key=lambda e: e[0])
    return by_category


def _window_candidates(target: dict, index: dict[int, list[tuple[float, dict]]],
                       window: int) -> list[dict]:
    """Approximate nearest neighbours by loan mix: the `window` banks either
    side of the target's own position in its dominant category's share-sorted
    list, PLUS the same window in the target's SECOND-largest category — a
    bank near an even split between two categories can have its closest real
    match sitting in either bucket, so searching only its single dominant
    category would miss it. Deterministic (no randomization), so results are
    reproducible run to run for the same population and window size."""
    vec = _vec(target)
    ranked_categories = sorted(range(len(vec)), key=lambda i: vec[i], reverse=True)
    seen: set = set()
    out: list[dict] = []
    for cat_idx in ranked_categories[:2]:
        entries = index.get(cat_idx, [])
        if not entries:
            continue
        shares = [e[0] for e in entries]
        pos = bisect.bisect_left(shares, vec[cat_idx])
        lo, hi = max(0, pos - window), min(len(entries), pos + window)
        for _, bank in entries[lo:hi]:
            cert = bank.get("cert_number")
            if cert not in seen:
                seen.add(cert)
                out.append(bank)
    return out


def rank_partners_approx(target: dict, index: dict[int, list[tuple[float, dict]]], *,
                         top_n: int = 10, footprints: dict | None = None,
                         window: int = 150) -> list[dict]:
    """Approximate-nearest-neighbour version of rank_partners(): narrow to a
    candidate set via `_window_candidates` (blocked on the loan-mix vector,
    business_similarity's real input and 25% of the default fit weight), then
    run the SAME exact fit_score() the naive sweep uses on only that reduced
    set — "exact scoring only for the retained candidates," per this repo's
    own audit backlog. Approximate by construction: a candidate with
    unremarkable business_similarity but an exceptional funding/size/geo fit
    could in principle sit in the true top-N while falling outside the
    window; the tradeoff is deliberate, not an oversight — re-scoring the
    full population for every one of the population's own banks is exactly
    the cost this function exists to avoid. `window` defaults large enough
    (150) that this is a genuinely close approximation in practice, not just
    a fast wrong answer — see the population-level agreement check in
    test_ma_fit.py.
    """
    candidates = _window_candidates(target, index, window)
    t_fp = (footprints or {}).get(target.get("cert_number"))
    out = []
    for cand in candidates:
        if cand.get("cert_number") == target.get("cert_number"):
            continue
        c_fp = (footprints or {}).get(cand.get("cert_number"))
        out.append(fit_score(target, cand, target_footprint=t_fp, cand_footprint=c_fp))
    out.sort(key=lambda r: r["fit_score"], reverse=True)
    return out[:top_n]


# ---- C9: weight validation against real deal history ---------------------

def _normalize_bank_name(name: str | None) -> str:
    """Coarse normalization for matching FDIC's `failures.BIDNAME` (free text)
    against a population bank's own `name` — strips common charter-type
    suffixes and punctuation. Exact-match only after normalization; this repo
    does not fuzzy-match below that (a wrong match would poison the deal
    sample with a fabricated transaction)."""
    if not name:
        return ""
    n = name.upper()
    for suf in (", NATIONAL ASSOCIATION", " NATIONAL ASSOCIATION", ", N A", " N A",
                ", F S B", " F S B", ", S S B", " S S B", ", S B", " S B"):
        n = n.replace(suf, "")
    n = n.replace(".", "").replace(",", "")
    return " ".join(n.split())


def match_deal_history(failures: list[dict], population_by_cert: dict[int, dict]) -> list[dict]:
    """C9 — real (target, acquirer) pairs from FDIC's own `failures` endpoint,
    already landed for B6/deposit_flight (docs/audit/04-remediation-prompts.md)
    — `BIDNAME` is the acquiring institution at resolution, not a new
    connector. `BIDNAME` is a free-text NAME, not a cert, so this matches it
    against `population_by_cert` (the SAME quarter's landed Gold population
    the deal should be evaluated against) by normalized exact name; an
    unmatched or AMBIGUOUS (>1 population bank normalizes to the same name)
    BIDNAME is dropped, not guessed at — every deal in the result is a real,
    confidently-identified transaction.
    """
    by_norm: dict[str, list[int]] = {}
    for cert, g in population_by_cert.items():
        by_norm.setdefault(_normalize_bank_name(g.get("name")), []).append(cert)

    deals = []
    for f in failures:
        if f.get("RESTYPE") != "FAILURE" or not f.get("BIDNAME"):
            continue
        target_cert = f.get("CERT")
        if target_cert not in population_by_cert:
            continue
        matches = by_norm.get(_normalize_bank_name(f.get("BIDNAME")), [])
        if len(matches) != 1 or matches[0] == target_cert:
            continue
        deals.append({"target_cert": target_cert, "acquirer_cert": matches[0],
                      "target_name": f.get("NAME"), "acquirer_name": f.get("BIDNAME"),
                      "fail_year": f.get("FAILYR")})
    return deals


def _acquirer_percentile(target: dict, acquirer_cert: int, population: list[dict], *,
                         footprints: dict | None = None, weights=DEFAULT_WEIGHTS) -> float | None:
    """Where the REAL acquirer's fit_score ranks among every OTHER candidate
    for this target (0-100) — the same "honest test" idea as
    deposit_flight.leave_one_out's percentile, applied to M&A fit instead of
    failure risk. ~50 is a coin flip; consistently above 50 across real deals
    is evidence the weights carry real signal."""
    t_fp = (footprints or {}).get(target.get("cert_number"))
    scores, acquirer_score = [], None
    for cand in population:
        c_num = cand.get("cert_number")
        if c_num == target.get("cert_number"):
            continue
        c_fp = (footprints or {}).get(c_num)
        s = fit_score(target, cand, target_footprint=t_fp, cand_footprint=c_fp, weights=weights)["fit_score"]
        scores.append(s)
        if c_num == acquirer_cert:
            acquirer_score = s
    if acquirer_score is None or not scores:
        return None
    below = sum(1 for s in scores if s < acquirer_score)
    return round(below / len(scores) * 100, 1)


def evaluate_weights(deals: list[dict], population_by_cert: dict[int, dict],
                     population_list: list[dict], *, footprints: dict | None = None,
                     weights=DEFAULT_WEIGHTS) -> dict:
    """C9 — mean/median acquirer percentile rank over every matched real deal,
    for one weight set. `deals` must already be scoped to the SAME quarter as
    `population_by_cert`/`population_list` (see match_deal_history)."""
    percentiles = []
    detail = []
    for d in deals:
        target = population_by_cert.get(d["target_cert"])
        if target is None or d["acquirer_cert"] not in population_by_cert:
            continue
        p = _acquirer_percentile(target, d["acquirer_cert"], population_list,
                                 footprints=footprints, weights=weights)
        if p is not None:
            percentiles.append(p)
            detail.append({**d, "acquirer_percentile": p})
    if not percentiles:
        return {"n": 0, "mean_percentile": None, "median_percentile": None, "deals": []}
    s = sorted(percentiles)
    return {
        "n": len(percentiles),
        "mean_percentile": round(sum(percentiles) / len(percentiles), 1),
        "median_percentile": s[len(s) // 2],
        "deals": detail,
    }


def refit_weights(deals: list[dict], population_by_cert: dict[int, dict],
                  population_list: list[dict], *, footprints: dict | None = None,
                  step: float = 0.1) -> dict:
    """C9 — coarse grid search over (funding, business, size, geo) weights
    (summing to 1, `step` increments — 0.1 keeps this a few hundred
    candidate weight sets, each a full evaluate_weights pass over the small
    real-deal sample, tractable in pure Python) maximizing mean acquirer
    percentile rank on the SAME deal sample DEFAULT_WEIGHTS is evaluated
    against. Returns the best candidate found and its score; the caller
    decides whether the improvement over DEFAULT_WEIGHTS clears a real
    margin before treating this as anything other than a documented
    alternative."""
    steps = [round(i * step, 2) for i in range(int(1 / step) + 1)]
    best = None
    for wf in steps:
        for wb in steps:
            if wf + wb > 1.0 + 1e-9:
                continue
            for ws in steps:
                if wf + wb + ws > 1.0 + 1e-9:
                    continue
                wg = round(1.0 - wf - wb - ws, 2)
                if wg < 0:
                    continue
                if wf + wb + ws == 0:
                    # Degenerate: every non-geo weight is 0. fit_score's no-geo
                    # renormalization (the caller here never passes footprints,
                    # so geo_overlap is always None and this branch always
                    # fires) divides by the sum of the REMAINING weights after
                    # dropping geo — 0/0 with nothing left to renormalize.
                    # Meaningless as a candidate anyway (100% of the score
                    # would ride on the one component that can never apply).
                    continue
                weights = {"funding": wf, "business": wb, "size": ws, "geo": wg}
                result = evaluate_weights(deals, population_by_cert, population_list,
                                          footprints=footprints, weights=weights)
                if result["n"] == 0:
                    continue
                if best is None or result["mean_percentile"] > best["mean_percentile"]:
                    best = {"weights": weights, **result}
    return best or {"weights": None, "n": 0, "mean_percentile": None}


# ---- C9: pro-forma calculator ---------------------------------------------

def pro_forma(target_silver: dict, acquirer_silver: dict, *,
              premium_to_tbv_pct: float = 20.0,
              cost_synergies_pct_of_target_opex: float = 30.0,
              tax_rate_pct: float = 21.0) -> dict:
    """C9 — a standard bank M&A pro-forma: combined assets, combined CET1
    ratio, goodwill created, tangible-book-value dilution and an earn-back
    period, built from real disclosed FDIC balance-sheet figures for BOTH
    sides plus three deal-structuring ASSUMPTIONS no source discloses (no
    public data publishes a deal price before a deal exists) — the premium
    over tangible book value, the cost-synergy share of the target's expense
    base, and the tax rate. Defaults are common industry rules of thumb, not
    fitted to real deal data; every assumption is echoed back in the result,
    never silently baked in.

    Without disclosed share-count or exchange-ratio data (FDIC's Call Report
    carries neither), this cannot compute a real PER-SHARE tangible-book-
    value dilution or EPS-accretion earn-back the way an investment bank's
    model would — both figures here are AGGREGATE proxies (dilution as a
    share of the acquirer's own tangible equity base; earn-back against the
    deal's aggregate after-tax synergy run-rate), named as such throughout.
    """
    from .stress import starting_position
    t_pos = starting_position(target_silver)
    a_pos = starting_position(acquirer_silver)

    t_assets = target_silver.get("total_assets") or 0.0
    a_assets = acquirer_silver.get("total_assets") or 0.0
    target_tbv = (target_silver.get("total_equity") or 0.0) - (target_silver.get("intangible_assets") or 0.0)
    acquirer_tbv = (acquirer_silver.get("total_equity") or 0.0) - (acquirer_silver.get("intangible_assets") or 0.0)

    deal_price = target_tbv * (1 + premium_to_tbv_pct / 100.0)
    goodwill_created = max(0.0, deal_price - target_tbv)

    combined_cet1_dollars = (t_pos.get("cet1_capital") or 0.0) + (a_pos.get("cet1_capital") or 0.0) - goodwill_created
    combined_rwa = (t_pos.get("rwa") or 0.0) + (a_pos.get("rwa") or 0.0)
    combined_cet1_ratio_pct = round(combined_cet1_dollars / combined_rwa * 100, 2) if combined_rwa else None

    tbv_dilution_pct = round(goodwill_created / acquirer_tbv * 100, 2) if acquirer_tbv else None

    target_opex = target_silver.get("noninterest_expense") or 0.0
    annual_synergy_after_tax = (target_opex * cost_synergies_pct_of_target_opex / 100.0
                                * (1 - tax_rate_pct / 100.0))
    earn_back_years = (round(goodwill_created / annual_synergy_after_tax, 1)
                       if annual_synergy_after_tax > 0 else None)

    return {
        "target": {"cert": target_silver.get("cert_number"), "name": target_silver.get("name"),
                   "total_assets": round(t_assets, 0), "tangible_book_value": round(target_tbv, 0)},
        "acquirer": {"cert": acquirer_silver.get("cert_number"), "name": acquirer_silver.get("name"),
                     "total_assets": round(a_assets, 0), "tangible_book_value": round(acquirer_tbv, 0)},
        "assumptions": {"premium_to_tbv_pct": premium_to_tbv_pct,
                        "cost_synergies_pct_of_target_opex": cost_synergies_pct_of_target_opex,
                        "tax_rate_pct": tax_rate_pct},
        "combined": {
            "combined_assets": round(t_assets + a_assets, 0),
            "deal_price": round(deal_price, 0),
            "goodwill_created": round(goodwill_created, 0),
            "combined_cet1_ratio_pct": combined_cet1_ratio_pct,
            "tangible_book_value_dilution_pct": tbv_dilution_pct,
            "annual_synergy_after_tax": round(annual_synergy_after_tax, 0),
            "earn_back_years": earn_back_years,
        },
        "note": ("Aggregate proxies, not per-share figures — FDIC's Call Report discloses no "
                 "share count or exchange ratio. Deal price, synergies and tax rate are "
                 "user-adjustable ASSUMPTIONS, not disclosed data."),
    }
