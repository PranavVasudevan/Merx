"""Gold layer — derived features every downstream feature/tool/agent reads.

The heart of "build once, reuse everywhere". Each function is a pure, testable
definition, pinned against real figures in the tests. When these move to
dbt/Spark (Phase 2), the reimplementation must reproduce the same numbers.

Phase-1b additions: loan-concentration ratios (feeds Feature 11 X-Ray),
CRE concentration, core-deposit ratio, and pass-through of FDIC capital ratios.
Still TODO (needs the peer population): ``percentile_rank_*``.
"""

from __future__ import annotations

# Loan categories we report concentration for: canonical column -> label.
#
# These MUST be mutually disjoint or the ratios don't sum to a book and the chart is
# a fabricated number. FDIC's RC-C schedule nests, and the nesting was verified
# empirically against all 1,038 banks in the landed population rather than assumed:
#
#   LNRE  (real_estate_loans) = construction + multifamily + nonfarm_nonres
#                               + residential_mortgage + farmland
#       -> reconciles for 99.2% of banks ONLY once HELOC is removed, because
#          LNRELOC (HELOC) is a SUBSET of LNRERES (1-4 family residential), which
#          includes revolving open-end lines. Verified exactly on Dime Community:
#          8.9395B - 0.0310B HELOC = 8.9086B = LNRE, to the dollar.
#   LNCON (consumer_loans)    ⊃ credit_card + auto + consumer_other, but those three
#          reconcile to the parent for only 36.6% of banks, so the TOTAL is the leaf
#          and the three are reported as sub-components.
#
# An earlier draft used 12 "categories" that double-counted parents and children and
# summed to 129.9% of the loan book on Wells Fargo. This 8-leaf set sums to a median
# 98.7% (p99 100.3%), the ~1.3% residual being leases and other loan types.
LOAN_CATEGORIES = {
    "construction_loans": "construction",
    "multifamily_loans": "multifamily",
    "nonfarm_nonres_loans": "nonfarm_nonres",
    "residential_mortgage_loans": "residential_mortgage",
    "farmland_loans": "farmland",
    "agricultural_loans": "agricultural",
    "c_and_i_loans": "c_and_i",
    "consumer_loans": "consumer",
}

# Reported alongside, but deliberately EXCLUDED from the concentration set above so
# nothing is counted twice: roll-ups of the leaves, and sub-components within one.
LOAN_ROLLUPS = {
    "cre_loans": "cre",                       # construction + multifamily + nonfarm_nonres
    "real_estate_loans": "real_estate",       # all five RE leaves
}
LOAN_SUBCOMPONENTS = {
    "heloc_loans": "heloc",                   # within residential_mortgage
    "credit_card_loans": "credit_card",       # within consumer
    "auto_loans": "auto",                     # within consumer
    "consumer_other_loans": "consumer_other",  # within consumer
}

# Size bands (B3: docs/audit/04-remediation-prompts.md — widening the landed
# population beyond the original $1B-$250B MVP slice made a flat population-wide
# percentile misleading again: a $1.2B bank and a $900B GSIB now sit in the same
# pool). Bounds are in whole USD, upper-bound-exclusive except the last band.
# Every population-wide figure (screener, leaderboard, peer percentiles) should
# be labelled with the band it covers; `percentile_rank_*_within_size` (C11) in
# peers.add_percentile_ranks is the band-conditional counterpart to the existing
# population-wide `percentile_rank_*` (a `_within_cluster` variant exists too).
ASSET_BANDS: list[tuple[str, float, float]] = [
    ("under_1b", 0.0, 1e9),
    ("1b_10b", 1e9, 10e9),
    ("10b_50b", 10e9, 50e9),
    ("50b_250b", 50e9, 250e9),
    ("over_250b", 250e9, float("inf")),
]


def asset_band(total_assets: float | None) -> str | None:
    """Which `ASSET_BANDS` bucket `total_assets` (whole USD) falls in, or None
    if assets aren't known."""
    if total_assets is None:
        return None
    for label, lo, hi in ASSET_BANDS:
        if lo <= total_assets < hi:
            return label
    return None


def _pct(numerator, denominator) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 4)


def uninsured_deposit_pct(row: dict) -> float | None:
    """Uninsured deposits as % of total deposits — the #1 deposit-flight signal.

    Uses FDIC's reported ``uninsured_deposits`` (DEPUNINS), not DEP - DEPINS.
    """
    return _pct(row.get("uninsured_deposits"), row.get("total_deposits"))


def core_deposit_pct(row: dict) -> float | None:
    """Core (stable, sticky) deposits as % of total. Higher = more stable funding."""
    return _pct(row.get("core_deposits"), row.get("total_deposits"))


def loan_to_deposit_pct(row: dict) -> float | None:
    """Net loans / total deposits. Validated against FDIC's reported LNLSDEPR."""
    return _pct(row.get("total_loans_net"), row.get("total_deposits"))


def equity_to_assets_pct(row: dict) -> float | None:
    """Total equity / total assets. Validated against FDIC's reported EQV."""
    return _pct(row.get("total_equity"), row.get("total_assets"))


def concentration_ratios(row: dict) -> dict:
    """Each loan category as % of gross loans. The core of Feature 11."""
    gross = row.get("total_loans_gross")
    out: dict = {}
    for col, label in LOAN_CATEGORIES.items():
        out[f"concentration_ratio_{label}"] = _pct(row.get(col), gross)
    return out


def max_concentration(concentrations: dict) -> tuple[str | None, float | None]:
    """The single most concentrated loan category and its ratio."""
    best_label, best_val = None, None
    for key, val in concentrations.items():
        if val is not None and (best_val is None or val > best_val):
            best_label, best_val = key.replace("concentration_ratio_", ""), val
    return best_label, best_val


def cre_to_equity_pct(row: dict) -> float | None:
    """CRE loans / total equity. A capital-relative concentration lens.

    NOTE: the precise supervisory 'CRE concentration' guideline uses *total
    risk-based capital* (not book equity) and excludes owner-occupied CRE. This
    equity-based proxy is transparent and directional until we ingest RWA/capital $.
    """
    return _pct(row.get("cre_loans"), row.get("total_equity"))


def cre_to_total_capital_pct(row: dict) -> float | None:
    """CRE loans / TOTAL RISK-BASED CAPITAL — the denominator the supervisory guidance
    actually specifies.

    The 2006 Interagency CRE Concentration Guidance (reaffirmed 2023) screens on CRE
    at or above 300% of total risk-based capital *together with* 50% growth over 36
    months. `cre_to_equity_pct` above uses book equity as a proxy, which runs high
    because equity is smaller than total risk-based capital. This is the real ratio.
    Returns None for CBLR electers and foreign branches, which report no total
    risk-based capital — see data_quality.capital_basis.
    """
    return _pct(row.get("cre_loans"), row.get("total_capital"))


def construction_to_total_capital_pct(row: dict) -> float | None:
    """Construction & land development / total risk-based capital. The guidance's
    *first* screening criterion is construction at or above 100% of capital — a
    separate, tighter test than the 300% total-CRE one."""
    return _pct(row.get("construction_loans"), row.get("total_capital"))


# ---- profitability -------------------------------------------------------
def net_interest_income(row: dict) -> float | None:
    ii, ie = row.get("interest_income"), row.get("interest_expense")
    return None if ii is None or ie is None else ii - ie


def noninterest_income_share_pct(row: dict) -> float | None:
    """Fee income as % of total revenue (net interest income + non-interest income).
    A high share means earnings lean on fees rather than the lending spread."""
    nii, fee = net_interest_income(row), row.get("noninterest_income")
    if nii is None or fee is None:
        return None
    return _pct(fee, nii + fee)


# ---- asset quality -------------------------------------------------------
def npl_ratio_pct(row: dict) -> float | None:
    """Noncurrent LOANS / gross LOANS. Uses NCLNLS (loan-level), deliberately not
    P3ASSET/P9ASSET, which are ASSET-level and would be a unit mismatch here."""
    return _pct(row.get("noncurrent_loans"), row.get("total_loans_gross"))


def net_charge_off_rate_pct(row: dict) -> float | None:
    return _pct(row.get("net_charge_offs"), row.get("total_loans_gross"))


def charge_off_rates_by_category(row: dict) -> dict:
    """C6 — per-category net-charge-off rate: net_charge_offs_<category> / that
    category's OWN gross loan balance, using the SAME disjoint 8-leaf set
    `concentration_ratios` uses (LOAN_CATEGORIES) — so a category's loss rate
    and its concentration share are directly comparable, not two different
    taxonomies. `None` per category where either side is undisclosed, never
    silently defaulted to the blended `net_charge_off_rate_pct`."""
    out: dict = {}
    for col, label in LOAN_CATEGORIES.items():
        out[f"charge_off_rate_pct_{label}"] = _pct(row.get(f"net_charge_offs_{label}"), row.get(col))
    return out


def allowance_to_loans_pct(row: dict) -> float | None:
    return _pct(row.get("allowance_for_credit_losses"), row.get("total_loans_gross"))


def allowance_coverage_pct(row: dict) -> float | None:
    """Allowance / noncurrent loans — reserves per dollar already gone bad. Under
    100% means the existing reserve doesn't cover loans already noncurrent."""
    return _pct(row.get("allowance_for_credit_losses"), row.get("noncurrent_loans"))


def texas_ratio_pct(row: dict) -> float | None:
    """(Noncurrent loans + OREO) / (tangible common equity + allowance).

    The classic bank-distress screen: above ~100% a bank's troubled assets exceed the
    resources available to absorb them. Tangible common equity is equity less
    intangibles — goodwill can't absorb a loss.
    """
    npl, oreo = row.get("noncurrent_loans"), row.get("other_real_estate_owned")
    equity, intangibles = row.get("total_equity"), row.get("intangible_assets")
    allowance = row.get("allowance_for_credit_losses")
    if npl is None or equity is None:
        return None
    troubled = npl + (oreo or 0)
    resources = equity - (intangibles or 0) + (allowance or 0)
    return _pct(troubled, resources) if resources and resources > 0 else None


# ---- funding composition -------------------------------------------------
def brokered_deposit_pct(row: dict) -> float | None:
    """Brokered deposits as % of total. Rate-shopping money that leaves fastest —
    a central mechanism in both the 2023 failures and the 2008 thrift collapses."""
    return _pct(row.get("brokered_deposits"), row.get("total_deposits"))


def large_denomination_deposit_pct(row: dict) -> float | None:
    """Deposits in accounts above the insurance limit, as % of total. Related to
    uninsured_deposit_pct but measured account-side rather than balance-side."""
    return _pct(row.get("large_denomination_deposits"), row.get("total_deposits"))


def time_deposit_pct(row: dict) -> float | None:
    return _pct(row.get("time_deposits"), row.get("total_deposits"))


def volatile_liability_pct(row: dict) -> float | None:
    """Volatile liabilities as % of assets — wholesale/short-term funding that can
    reprice or vanish under stress."""
    return _pct(row.get("volatile_liabilities"), row.get("total_assets"))


def qoq_delta(current, previous) -> dict | None:
    if current is None or previous is None:
        return None
    abs_change = current - previous
    pct_change = round(abs_change / previous * 100, 4) if previous else None
    return {"abs": abs_change, "pct": pct_change}


def quarters_before(quarter: str, n: int) -> str:
    """``quarter`` minus ``n`` quarters, e.g. ("2026Q1", 12) -> "2023Q1"."""
    year, q = int(quarter[:4]), int(quarter[5])
    total = year * 4 + (q - 1) - n
    y, qi = divmod(total, 4)
    return f"{y}Q{qi + 1}"


def growth_rate_nyr(history_desc: list[dict], years: int, field: str) -> float | None:
    """Annualized (CAGR) growth in ``field`` over ``years``, from a bank's own
    Silver/Gold history (newest-first, current quarter first).

    Requires a row landed exactly ``years * 4`` quarters before the current one —
    no interpolation, so a gap in filing history correctly yields ``None`` rather
    than a fabricated rate. Also ``None`` if the anchor value isn't a positive
    number (CAGR is undefined for a zero/negative base).
    """
    if not history_desc:
        return None
    current = history_desc[0]
    quarter = current.get("quarter")
    if not quarter:
        return None
    target = quarters_before(quarter, years * 4)
    anchor = next((r for r in history_desc if r.get("quarter") == target), None)
    if anchor is None:
        return None
    cur_val, past_val = current.get(field), anchor.get(field)
    if cur_val is None or past_val is None or past_val <= 0:
        return None
    return round(((cur_val / past_val) ** (1 / years) - 1) * 100, 4)


def _trend_slope(values: list[float | None]) -> float | None:
    """OLS slope of `values` (index = time, oldest first) — ratio-points per
    quarter. `None` with fewer than 2 non-None points; a fabricated flat trend
    from 0 or 1 real observations would be worse than an honest gap."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return None
    n = len(pts)
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    den = sum((p[0] - mean_x) ** 2 for p in pts)
    if den == 0:
        return None
    num = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts)
    return round(num / den, 4)


def credit_trajectory(history_desc: list[dict], *, window: int = 4) -> dict:
    """C8 — per-bank credit-quality trajectory from up to `window` quarters of
    its own landed Silver history (`history_desc[0]` = current quarter,
    newest-first — same convention `growth_rate_nyr` uses). NPL ratio,
    net-charge-off rate and allowance coverage are single-quarter SNAPSHOTS
    everywhere else in the product; this is the trend/acceleration view B1's
    backfill makes possible.

    `npl_acceleration`: recent-half OLS slope minus earlier-half slope — a
    rough second derivative, needs at least 4 quarters to split. `None` per
    field with too little landed history, never a fabricated flat trend.

    `deterioration_flag`: true only when at least 2 of the 3 signals that ARE
    available (NPL trending up, NCO trending up, allowance coverage trending
    down) move adversely together — a single noisy metric shouldn't flag a
    bank alone.
    """
    quarters = history_desc[:window]
    asc = list(reversed(quarters))  # oldest -> newest, for slope direction
    npl = [npl_ratio_pct(r) for r in asc]
    nco = [net_charge_off_rate_pct(r) for r in asc]
    allow = [allowance_coverage_pct(r) for r in asc]

    npl_trend, nco_trend, allow_trend = _trend_slope(npl), _trend_slope(nco), _trend_slope(allow)

    npl_accel = None
    if len(asc) >= 4:
        half = len(asc) // 2
        early, recent = _trend_slope(npl[:half]), _trend_slope(npl[half:])
        if early is not None and recent is not None:
            npl_accel = round(recent - early, 4)

    adverse = signals = 0
    for trend, adverse_if in ((npl_trend, lambda t: t > 0), (nco_trend, lambda t: t > 0),
                              (allow_trend, lambda t: t < 0)):
        if trend is not None:
            signals += 1
            if adverse_if(trend):
                adverse += 1

    return {
        "npl_trend_pp_per_qtr": npl_trend,
        "npl_acceleration": npl_accel,
        "net_charge_off_trend_pp_per_qtr": nco_trend,
        "allowance_coverage_trend_pp_per_qtr": allow_trend,
        "deterioration_signal_count": adverse,
        "deterioration_signals_available": signals,
        "deterioration_flag": signals >= 2 and adverse >= 2,
        "trajectory_quarters": len(quarters),
    }


# ---- C15: quarter-isolated profitability ratios ---------------------------

def quarter_number(quarter: str | None) -> int | None:
    """"2026Q1" -> 1. None if `quarter` isn't that shape — same convention as
    stress.estimate_ppnr_quarterly (C4) and market.quarter_end_date (C10)."""
    if not quarter or len(quarter) != 6 or quarter[4] != "Q":
        return None
    try:
        q = int(quarter[5])
    except ValueError:
        return None
    return q if 1 <= q <= 4 else None


def _quarterly_isolated_flow(row: dict, prev: dict | None, field: str) -> float | None:
    """This quarter's own dollar flow, un-cumulated from FDIC's YTD-cumulative
    field. Q1: YTD IS the quarter, no adjustment needed. Q2-Q4: YTD(this) -
    YTD(prev) — needs `prev` to be the immediately preceding quarter of the
    SAME calendar year (the normal case for `gold_features`' `prev` argument).
    `None` if the quarter can't be parsed, the field is undisclosed, or (for
    Q2-Q4) `prev` is missing or from a different year (a landing gap, never
    guessed across)."""
    ytd = row.get(field)
    if ytd is None:
        return None
    qnum = quarter_number(row.get("quarter"))
    if qnum is None:
        return None
    if qnum == 1:
        return ytd
    if prev is None:
        return None
    if (prev.get("quarter") or "")[:4] != (row.get("quarter") or "")[:4]:
        return None
    prev_ytd = prev.get(field)
    return None if prev_ytd is None else ytd - prev_ytd


def quarterly_isolated_ratios(row: dict, prev: dict | None = None) -> dict:
    """C15 — FDIC's NIM/ROA/ROE/efficiency ratios are year-to-date annualized,
    so a Q1 figure and a Q4 figure for the SAME bank are not directly
    comparable on a trend chart (Q4 blends the whole year; Q1 is one
    quarter). Computes QUARTER-ISOLATED versions (this quarter alone,
    annualized x4 for the flow-over-stock ratios) from the YTD dollar
    deltas, where the inputs allow — `None`, never a guess, whenever `prev`
    is missing/mismatched or a required YTD field is undisclosed.

    Denominators use `average_assets`/`total_equity` (point-in-time equity —
    no average-equity field is landed), the same proxy-vs-precise tradeoff
    this module already documents for `cre_to_equity_pct`. NIM's true
    denominator is average EARNING assets specifically, not average total
    assets; no earning-assets field is landed either, so this uses
    average_assets as a proxy — real, but directionally understated versus
    FDIC's own earning-assets-based NIM.
    """
    ni = _quarterly_isolated_flow(row, prev, "net_income")
    ii = _quarterly_isolated_flow(row, prev, "interest_income")
    ie = _quarterly_isolated_flow(row, prev, "interest_expense")
    nonii = _quarterly_isolated_flow(row, prev, "noninterest_income")
    nonix = _quarterly_isolated_flow(row, prev, "noninterest_expense")
    nii_flow = None if (ii is None or ie is None) else ii - ie

    avg_assets, equity = row.get("average_assets"), row.get("total_equity")

    def _annualized_pct(numerator, denominator):
        return None if (numerator is None or not denominator) else round(numerator * 4 / denominator * 100, 3)

    efficiency = None
    if nonix is not None and nii_flow is not None and nonii is not None and (nii_flow + nonii):
        efficiency = round(nonix / (nii_flow + nonii) * 100, 3)  # ratio of two same-quarter flows, not annualized

    return {
        "roa_pct_quarterly": _annualized_pct(ni, avg_assets),
        "roe_pct_quarterly": _annualized_pct(ni, equity),
        "net_interest_margin_pct_quarterly": _annualized_pct(nii_flow, avg_assets),
        "efficiency_ratio_pct_quarterly": efficiency,
    }


def gold_features(row: dict, prev: dict | None = None, history: list[dict] | None = None) -> dict:
    """Derive one Gold feature row from a Silver row (+ optional prior quarter).

    Pass ``prev=None`` for cross-sectional use (a population of many banks in one
    quarter), where QoQ deltas don't apply. ``history`` — this bank's own Silver
    rows newest-first, starting with ``row`` itself — enables the trailing
    ``growth_rate_3yr_pct`` fields; omit it where only one quarter is available.
    """
    conc = concentration_ratios(row)
    max_label, max_val = max_concentration(conc)
    gross = row.get("total_loans_gross")
    rollups = {f"concentration_ratio_{label}": _pct(row.get(col), gross)
               for col, label in LOAN_ROLLUPS.items()}
    subs = {f"concentration_ratio_{label}": _pct(row.get(col), gross)
            for col, label in LOAN_SUBCOMPONENTS.items()}
    return {
        "cert_number": row.get("cert_number"),
        "name": row.get("name"),
        "quarter": row.get("quarter"),
        "total_assets": row.get("total_assets"),
        "asset_band": asset_band(row.get("total_assets")),
        # deposits / funding
        "uninsured_deposit_pct": uninsured_deposit_pct(row),
        "core_deposit_pct": core_deposit_pct(row),
        "loan_to_deposit_pct": loan_to_deposit_pct(row),
        "equity_to_assets_pct": equity_to_assets_pct(row),
        "brokered_deposit_pct": brokered_deposit_pct(row),
        "large_denomination_deposit_pct": large_denomination_deposit_pct(row),
        "time_deposit_pct": time_deposit_pct(row),
        "volatile_liability_pct": volatile_liability_pct(row),
        "loans_to_core_deposits_pct": row.get("loans_to_core_deposits_reported"),
        # concentration (Feature 11 inputs). `conc` is the DISJOINT leaf set that
        # max_concentration ranks over; rollups/subs are reported but never ranked,
        # so a parent can't beat its own child.
        **conc, **rollups, **subs,
        "max_loan_concentration_category": max_label,
        "max_loan_concentration_pct": max_val,
        "cre_to_equity_pct": cre_to_equity_pct(row),
        "cre_to_total_capital_pct": cre_to_total_capital_pct(row),
        "construction_to_total_capital_pct": construction_to_total_capital_pct(row),
        # profitability
        "net_interest_margin_pct": row.get("net_interest_margin_reported"),
        "roa_pct": row.get("roa_reported"),
        "roe_pct": row.get("roe_reported"),
        "efficiency_ratio_pct": row.get("efficiency_ratio_reported"),
        # C15 — quarter-isolated counterparts of the four YTD-annualized
        # ratios above (None when prev is None/mismatched — same "no prior
        # quarter, no QoQ" contract as qoq_delta below).
        **quarterly_isolated_ratios(row, prev),
        "net_interest_income": net_interest_income(row),
        "noninterest_income_share_pct": noninterest_income_share_pct(row),
        # asset quality
        "npl_ratio_pct": npl_ratio_pct(row),
        "net_charge_off_rate_pct": net_charge_off_rate_pct(row),
        # C6 — per-category loss rates (concentration_ratio_<label>'s size
        # counterpart), feeds stress.apply_category_loan_losses.
        **charge_off_rates_by_category(row),
        "allowance_to_loans_pct": allowance_to_loans_pct(row),
        "allowance_coverage_pct": allowance_coverage_pct(row),
        "texas_ratio_pct": texas_ratio_pct(row),
        "noncurrent_assets_ratio_pct": row.get("noncurrent_assets_ratio_reported"),
        # EU banks only (B2, from EBA's tr_cre.csv credit-risk cube — see
        # banklens_transforms.silver_eba); None for FDIC-sourced rows, same
        # "disclose absence, don't fabricate" contract as every other EU-only gap.
        "npl_ratio_pct_supervisory": row.get("npl_ratio_pct_supervisory"),
        "sector_concentration_hhi": row.get("sector_concentration_hhi"),
        "sector_concentration_top_sector": row.get("sector_concentration_top_sector"),
        "sector_concentration_top_pct": row.get("sector_concentration_top_pct"),
        # capital adequacy (straight from FDIC)
        "cet1_ratio": row.get("cet1_ratio"),
        "tier1_rbc_ratio": row.get("tier1_rbc_ratio"),
        "total_rbc_ratio": row.get("total_rbc_ratio"),
        "leverage_ratio": row.get("leverage_ratio"),
        # trend (None when prev is None)
        "qoq_total_deposits": qoq_delta(
            row.get("total_deposits"), prev.get("total_deposits") if prev else None),
        "qoq_uninsured_deposit_pct": qoq_delta(
            uninsured_deposit_pct(row), uninsured_deposit_pct(prev) if prev else None),
        # trailing growth (None until 3 years of quarterly history has landed)
        "growth_rate_3yr_pct": growth_rate_nyr(history, 3, "total_assets") if history else None,
        "deposit_growth_rate_3yr_pct": growth_rate_nyr(history, 3, "total_deposits") if history else None,
        # C8 — credit-quality trajectory (trend/acceleration, not just a
        # single-quarter snapshot); works with as few as 2 landed quarters,
        # richer with more (see credit_trajectory).
        **credit_trajectory(history or []),
    }


def derive_gold(silver_rows_desc: list[dict]) -> list[dict]:
    """One bank's Silver rows (newest-first) -> Gold rows, with QoQ from the prior quarter
    and trailing 3yr growth from its own longer history."""
    return [
        gold_features(
            row,
            silver_rows_desc[i + 1] if i + 1 < len(silver_rows_desc) else None,
            history=silver_rows_desc[i:],
        )
        for i, row in enumerate(silver_rows_desc)
    ]
