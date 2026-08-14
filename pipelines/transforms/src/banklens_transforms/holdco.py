"""Holding-company Silver layer (B4: docs/audit/04-remediation-prompts.md).

Normalises the three Fed NIC bulk files (`banklens_ingestion.sources.fed_nic`)
into one queryable shape: which RSSDs are bank holding companies, what each
one's consolidated financials are for a quarter, and — the actual point —
which bank CHARTERS (FDIC CERTs) roll up to which HOLDING COMPANY, so a bank
page can show "this charter" next to "the group it belongs to."

The join key throughout is the RSSD ID: FDIC's own population records carry
the bank's holding company's RSSD as `RSSDHCR` (surfaced by
`banklens_transforms.silver.to_bank_financials` as `holding_company_rssd`),
and Fed NIC's own `attributes`/`relationships`/`financials` files are all
keyed by RSSD natively — no fuzzy matching needed, unlike the CERT<->CIK
crosswalk (banklens_transforms.crosswalk), which exists specifically because
FDIC and SEC do NOT share a common identifier.
"""

from __future__ import annotations

from collections import defaultdict


_THOUSANDS = 1_000

# Fed NIC reports dollar amounts in $ THOUSANDS (same convention as FDIC's raw
# Bronze); ratios are already percentages. Scaled to whole USD here, at Silver
# time, so a caller comparing `charter_level.total_assets` (whole USD, from
# `silver.to_bank_financials`) against `holding_company.total_assets` sees
# real numbers side by side rather than off by 1000x.
_DOLLAR_FIELDS = ("total_assets", "total_liabilities", "total_equity_capital",
                  "risk_weighted_assets", "tier1_capital", "total_capital",
                  "net_income", "goodwill")
_RATIO_FIELDS = ("cet1_ratio", "tier1_capital_ratio", "total_capital_ratio",
                 "tier1_leverage_ratio")


def to_holdco_row(financials: dict, attributes: dict | None) -> dict:
    """One holding company's Silver row: `financials` is one row from
    `FedNicSource.fetch_financials` (already curated/typed), `attributes` is
    the matching row from `fetch_attributes` (name), or None if this RSSD
    filed Y-9C financials but isn't in the active-BHC attributes snapshot
    (e.g. it existed at filing time but has since been merged out — real,
    disclosed as `name: None`, not dropped)."""
    row = {
        "rssd": financials["rssd"],
        "period": financials["period"],
        "name": (attributes or {}).get("NM_LGL") or None,
        "short_name": (attributes or {}).get("NM_SHORT") or None,
    }
    for f in _DOLLAR_FIELDS:
        v = financials.get(f)
        row[f] = v * _THOUSANDS if v is not None else None
    for f in _RATIO_FIELDS:
        row[f] = financials.get(f)
    return row


def build_holdco_table(financials_rows: list[dict], attribute_rows: list[dict]) -> dict[int, dict]:
    """{rssd: holdco_row} for one landed quarter's `financials_rows`. Dollar
    amounts are normalised to whole USD (see `to_holdco_row`) — Fed NIC's own
    Bronze bytes stay in $ thousands, matching every other connector's
    "Bronze raw, Silver normalised" contract."""
    attrs_by_rssd = {a["ID_RSSD"]: a for a in attribute_rows if a.get("ID_RSSD")}
    out = {}
    for f in financials_rows:
        rssd = f.get("rssd")
        if not rssd:
            continue
        try:
            rssd_int = int(rssd)
        except ValueError:
            continue
        out[rssd_int] = to_holdco_row(f, attrs_by_rssd.get(rssd))
    return out


def build_subsidiary_index(relationship_rows: list[dict]) -> dict[int, list[int]]:
    """{parent_rssd: [offspring_rssd, ...]} from `FedNicSource.fetch_relationships`
    (already filtered to open, controlling edges — see that function's
    docstring). One level of the tree, not the full transitive closure: a
    holding company two levels down (a sub-holding-company's own subsidiary)
    needs walking this index again from its own parent, deliberately not
    flattened here so a caller can see the real structure rather than a
    pre-collapsed list."""
    out: dict[int, list[int]] = defaultdict(list)
    for r in relationship_rows:
        parent, child = r.get("ID_RSSD_PARENT"), r.get("ID_RSSD_OFFSPRING")
        if parent and child:
            try:
                out[int(parent)].append(int(child))
            except ValueError:
                continue
    return dict(out)


def build_parent_index(relationship_rows: list[dict]) -> dict[int, int]:
    """{offspring_rssd: parent_rssd} — the inverse of `build_subsidiary_index`,
    for "what does THIS entity roll up to" lookups (the common case: a bank
    page has one charter's RSSD and wants its holding company, not the other
    way round). An RSSD with more than one open controlling parent (data
    anomaly, not expected but not asserted-impossible) keeps the LAST one
    seen rather than raising — real Bronze data over a strict invariant."""
    out: dict[int, int] = {}
    for r in relationship_rows:
        parent, child = r.get("ID_RSSD_PARENT"), r.get("ID_RSSD_OFFSPRING")
        if parent and child:
            try:
                out[int(child)] = int(parent)
            except ValueError:
                continue
    return out
