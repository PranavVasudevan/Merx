"""Real duration/convexity/re-pricing for the AFS/HTM securities book, via
the actual compiled QuantLib C++ library (its official SWIG-generated Python
bindings — `pip install QuantLib`, a prebuilt wheel, no separate C++ build
needed on this machine). This replaces `stress.py`'s rate-shock calculation,
which is a plain linear "modified duration times yield change" approximation,
with genuine discounted-cash-flow bond pricing.

Why bindings, not a from-scratch C++/Rust rewrite of bond math: the user's
own framing for this work-stream was "C++/QuantLib binding" — QuantLib is a
20+ year old, extensively validated fixed-income pricing library; the
responsible engineering choice is to USE it, not to re-derive DCF pricing
and Newton-Raphson yield solving from first principles. The bindings call
straight into the real compiled C++ engine (FixedRateBond, DiscountingBondEngine,
BondFunctions::duration/convexity all live in QuantLib's C++ source) — this
is not a Python reimplementation wearing a QuantLib label.

Honest modeling scope: an FDIC call report gives one AFS dollar total and one
HTM dollar total per bank, not holdings-level detail (individual bonds,
coupons, maturities). Both this module and `stress.py`'s existing linear
approximation already assume a single "average duration" per book (the
`afs_duration`/`htm_duration` Shock fields, in years) — this module goes
further by building one REPRESENTATIVE bullet bond with that many years to
maturity, priced under an assumed flat yield curve, and re-pricing it under
the shocked curve. That is a real DCF re-price (not a Taylor-series
approximation), but it is still a single-bond proxy for a book that in
reality holds many different instruments — not a claim of holdings-level
accuracy.
"""

from __future__ import annotations

import QuantLib as ql

_DAY_COUNT = ql.Actual365Fixed()
_CALENDAR = ql.NullCalendar()
_EVAL_DATE = ql.Date(1, 1, 2026)


def _build_bond(maturity_years: float, coupon: float) -> ql.FixedRateBond:
    maturity_years = max(1, round(maturity_years))
    schedule = ql.Schedule(
        _EVAL_DATE, _EVAL_DATE + ql.Period(maturity_years, ql.Years),
        ql.Period(ql.Semiannual), _CALENDAR, ql.Unadjusted, ql.Unadjusted,
        ql.DateGeneration.Forward, False,
    )
    return ql.FixedRateBond(0, 100.0, schedule, [coupon], _DAY_COUNT)


def _price_at(bond: ql.FixedRateBond, yield_level: float) -> float:
    curve = ql.FlatForward(_EVAL_DATE, yield_level, _DAY_COUNT, ql.Compounded, ql.Semiannual)
    bond.setPricingEngine(ql.DiscountingBondEngine(ql.YieldTermStructureHandle(curve)))
    return bond.NPV()


def reprice_under_shock(maturity_years: float, base_yield: float, rate_shock_bps: float) -> dict:
    """Build one representative bullet bond (coupon = base_yield, so it prices
    at par under the base curve), price it, then re-price it under the
    shocked curve. Returns the actual DCF price-change percentage, alongside
    QuantLib's own computed modified duration and convexity for that bond
    (informational — see module docstring: these come out somewhat below
    `maturity_years` because a coupon bond's duration is always less than its
    maturity, unlike the caller's plain "assumed duration" input).

    `ql.Settings.instance().evaluationDate` is process-global mutable state in
    QuantLib — set unconditionally on every call so this function is safe to
    call from any order/thread without depending on a prior call's side effect.
    """
    ql.Settings.instance().evaluationDate = _EVAL_DATE
    if maturity_years <= 0 or base_yield <= 0:
        return {"modified_duration": 0.0, "convexity": 0.0, "price_change_pct": 0.0,
               "base_price": 100.0, "shocked_price": 100.0}

    bond = _build_bond(maturity_years, base_yield)
    base_price = _price_at(bond, base_yield)
    shocked_yield = base_yield + rate_shock_bps / 10000.0
    shocked_price = _price_at(bond, shocked_yield)

    rate = ql.InterestRate(base_yield, _DAY_COUNT, ql.Compounded, ql.Semiannual)
    mod_dur = ql.BondFunctions.duration(bond, rate, ql.Duration.Modified)
    convexity = ql.BondFunctions.convexity(bond, rate)

    return {
        "modified_duration": round(mod_dur, 4),
        "convexity": round(convexity, 4),
        "price_change_pct": round((shocked_price - base_price) / base_price, 6),
        "base_price": round(base_price, 4),
        "shocked_price": round(shocked_price, 4),
    }


def loss_from_reprice(book_value: float, maturity_years: float, base_yield: float,
                      rate_shock_bps: float) -> float:
    """Dollar mark-to-market loss on `book_value` implied by a real QuantLib
    re-price — the drop-in replacement for stress.py's
    `book_value * duration_years * (rate_shock_bps / 10000)` linear formula.
    Returns a positive number when yields rise (a loss), matching the sign
    convention `afs_loss`/`htm_unrealized` already use in stress.py.
    """
    if book_value <= 0:
        return 0.0
    result = reprice_under_shock(maturity_years, base_yield, rate_shock_bps)
    return -book_value * result["price_change_pct"]
