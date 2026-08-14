"""Data access for the MCP tools — loads the landed Bronze, builds the Gold
feature layer + peer percentiles + behavioral clusters once, and caches it.

The MCP server is thin: it reads the SAME Gold/feature logic the CLI and (later)
the UI use. No business logic lives here that isn't already in banklens_transforms.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import defaultdict
from pathlib import Path

import duckdb

from banklens_transforms import clustering
from banklens_transforms.footprint import build_footprints, county_deposit_table, decode_cell
from banklens_transforms.gold import gold_features
from banklens_transforms.holdco import build_holdco_table, build_parent_index
from banklens_transforms.ma_fit import rank_partners
from banklens_transforms.market import to_price_bar
from banklens_transforms.peers import add_percentile_ranks
from banklens_transforms.silver import to_bank_financials
from banklens_transforms.silver_eba import to_bank_financials_eba

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
_POP_DIR = DATA / "bronze" / "source=fdic" / "population"
_CROSSWALK = DATA / "silver" / "crosswalk.json"
_SOD = DATA / "bronze" / "source=fdic" / "sod" / "year=2025" / "records.json"
_EBA_INSTITUTIONS = DATA / "bronze" / "source=eba" / "institutions" / "records.json"
_EBA_FINANCIALS = DATA / "bronze" / "source=eba" / "financials" / "records.json"
_EBA_CREDIT_RISK = DATA / "bronze" / "source=eba" / "credit_risk" / "records.json"
_FX_EUR_USD = DATA / "bronze" / "source=fx" / "eur_usd" / "records.json"
_FED_NIC_DIR = DATA / "bronze" / "source=fed_nic"
_FED_NIC_ATTRS = _FED_NIC_DIR / "attributes" / "records.json"
_FED_NIC_RELATIONSHIPS = _FED_NIC_DIR / "relationships" / "records.json"
_FRED_DIR = DATA / "bronze" / "source=fred"

_CLUSTER_METRICS = ["concentration_ratio_cre", "concentration_ratio_c_and_i",
                    "concentration_ratio_residential_mortgage", "uninsured_deposit_pct",
                    "core_deposit_pct"]
# The training-only historical cross-sections. They carry a REDUCED 15-field set
# (landed for the deposit-flight model, not for analytics) so they must never be
# picked up as "the current quarter" or as a QoQ comparison base.
_TRAINING_ONLY_QUARTERS = {"20221231", "20080331"}

_cache: dict = {}

# When set, every function below reads from the materialized DuckDB artifact
# gold_db_cli.py produces instead of walking Bronze JSON under DATA — the
# free-hosting path (see docs/audit/04-remediation-prompts.md A5): no
# data/bronze/ mount needed at all. Falls back to the JSON path when unset,
# so local dev (and every existing script) is unchanged.
_GOLD_DB = os.environ.get("BANKLENS_GOLD_DB")

# See gold_db_cli.py's module docstring — the only Gold fields that are ever a
# nested dict rather than a scalar (gold.qoq_delta); flattened to JSON text at
# materialization time so every other field can round-trip through DuckDB as a
# plain scalar with no type-inference risk.
_NESTED_GOLD_FIELDS = ("qoq_total_deposits", "qoq_uninsured_deposit_pct")


def _gold_conn() -> duckdb.DuckDBPyConnection | None:
    """Read-only connection to the BANKLENS_GOLD_DB artifact, or None (the
    JSON/Bronze path) if that env var isn't set. Cached for the process
    lifetime, same as every other accessor in this module."""
    if not _GOLD_DB:
        return None
    if "gold_conn" not in _cache:
        _cache["gold_conn"] = duckdb.connect(_GOLD_DB, read_only=True)
    return _cache["gold_conn"]


def _rows(conn: duckdb.DuckDBPyConnection, sql: str, params: list | tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _unflatten_gold_row(row: dict) -> dict:
    for k in _NESTED_GOLD_FIELDS:
        v = row.get(k)
        if isinstance(v, str):
            row[k] = json.loads(v)
    return row


def _footprint_from_row(row: dict) -> dict:
    cells = {decode_cell(c) for c in json.loads(row["cells_json"])}
    deposits_by_cell = {decode_cell(k): v for k, v in json.loads(row["deposits_by_cell_json"]).items()}
    centroid = ((row["centroid_lat"], row["centroid_lon"])
               if row.get("centroid_lat") is not None else None)
    return {
        "cert": row["cert_number"], "branch_count": row["branch_count"], "cells": cells,
        "deposits_by_cell": deposits_by_cell, "total_deposits": row["total_deposits"],
        "centroid": centroid, "geo_basis": row["geo_basis"],
        "counties": set(json.loads(row["counties_json"])),
        "states": set(json.loads(row["states_json"])),
    }


def _county_from_row(row: dict) -> dict:
    return {
        "fips": row["fips"], "name": row.get("name"), "state": row.get("state"),
        "total_deposits": row.get("total_deposits") or 0.0,
        "branch_count": row.get("branch_count") or 0,
        "by_cert": {int(k): v for k, v in json.loads(row["by_cert_json"]).items()},
    }


# Bounds population()'s `pop:<quarter>` cache entries — the heaviest structure
# this module caches (every bank's full computed Gold row, including
# percentile ranks and cluster assignment, for the whole population).
# Nothing evicted ANY quarter before this: every quarter ever requested
# stayed resident in `_cache` for the process lifetime, which is fine at
# today's 8 landed quarters but stops being fine as more get backfilled.
#
# Deliberately NOT applied to _silver_for()'s `silver:<quarter>` entries:
# bank_history()/get_bank_trends()/get_quarterly_briefing() each sweep EVERY
# landed quarter in one call, and a bare Silver row (no percentiles/cluster
# fields) is far smaller than a fully Gold-computed one — capping that cache
# too would thrash on every multi-quarter call for little memory benefit.
_MAX_CACHED_QUARTERS = int(os.environ.get("BANKLENS_MAX_CACHED_QUARTERS", "3"))
_pop_cache_order: list[str] = []   # least-recently-used first


def _note_pop_cache_use(repdte: str) -> None:
    if repdte in _pop_cache_order:
        _pop_cache_order.remove(repdte)
    _pop_cache_order.append(repdte)
    while len(_pop_cache_order) > _MAX_CACHED_QUARTERS:
        evict = _pop_cache_order.pop(0)
        _cache.pop(f"pop:{evict}", None)


def available_quarters() -> list[str]:
    """Landed analytical population quarters, newest first (REPDTE strings).

    Discovered by glob rather than hardcoded — this used to pin `repdte=20260331`,
    which made every multi-quarter view impossible. When BANKLENS_GOLD_DB is set,
    discovered from the artifact's `gold.pop_quarter` column instead of Bronze.
    """
    if "quarters" not in _cache:
        conn = _gold_conn()
        if conn is not None:
            found = [r[0] for r in conn.execute(
                "SELECT DISTINCT pop_quarter FROM gold ORDER BY pop_quarter DESC").fetchall()]
        else:
            found = sorted((p.name.split("=", 1)[1] for p in _POP_DIR.glob("repdte=*")
                            if p.is_dir() and any(p.glob("landed=*/records.json"))), reverse=True)
        _cache["quarters"] = [q for q in found if q not in _TRAINING_ONLY_QUARTERS]
    return _cache["quarters"]


def _pop_snapshots(repdte: str) -> list[str]:
    """Every landing DATE (YYYYMMDD, ascending) available for one `repdte`
    partition — B9 (docs/audit/04-remediation-prompts.md): FDIC restates prior
    quarters, and Bronze is append-only, so `population/repdte=X/landed=Y/`
    can hold more than one snapshot of the same REPDTE over time (one per
    re-land) instead of the newest silently overwriting the last."""
    d = _POP_DIR / f"repdte={repdte}"
    if not d.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in d.glob("landed=*") if (p / "records.json").exists())


def _pop_snapshot_path(repdte: str, as_of: str | None) -> Path | None:
    """The Bronze partition for `repdte` as it stood on `as_of` (YYYYMMDD) —
    the LATEST landing dated on or before `as_of`, matching what a user
    querying on that date would actually have seen. `as_of=None` (the default
    everywhere) means "the newest snapshot", i.e. today's behavior, unchanged.
    `None` is also returned when no snapshot yet existed as of that date
    (querying a REPDTE from before it was first landed) — the honest answer,
    not the nearest snapshot regardless of direction."""
    snaps = _pop_snapshots(repdte)
    if not snaps:
        return None
    chosen = snaps[-1] if as_of is None else next((s for s in reversed(snaps) if s <= as_of), None)
    if chosen is None:
        return None
    return _POP_DIR / f"repdte={repdte}" / f"landed={chosen}" / "records.json"


def latest_quarter() -> str | None:
    qs = available_quarters()
    return qs[0] if qs else None


def previous_quarter(repdte: str) -> str | None:
    """The landed quarter immediately before `repdte`, or None."""
    qs = available_quarters()
    if repdte not in qs:
        return None
    i = qs.index(repdte)
    return qs[i + 1] if i + 1 < len(qs) else None


def _silver_for(repdte: str, as_of: str | None = None) -> list[dict]:
    """US-only Silver rows for one landed quarter — deliberately excludes EU
    banks even when BANKLENS_GOLD_DB is set (filtered on origin='us'): EU rows
    are unioned into every US quarter's `silver` table at materialization time
    (see gold_db_cli.py), the same way population() unions `_eu_silver()` into
    every quarter live, and callers of this function (population(), and
    bank_history() per-quarter) both expect the pre-union, US-only shape.

    `as_of` (B9, YYYYMMDD): pick the Bronze snapshot as it stood on that
    landing date rather than the newest — see `_pop_snapshot_path`. Only
    honored on the JSON/Bronze path; the materialized DuckDB artifact
    (BANKLENS_GOLD_DB) holds only the latest snapshot, so an `as_of` request
    against it fails loudly rather than silently answering with "latest".
    """
    key = f"silver:{repdte}:{as_of or 'latest'}"
    if key not in _cache:
        conn = _gold_conn()
        if conn is not None:
            if as_of is not None:
                raise ValueError(
                    "as_of point-in-time queries need the JSON/Bronze path "
                    "(BANKLENS_GOLD_DB unset) — the materialized DuckDB artifact "
                    "only ever holds the latest landed snapshot of each quarter.")
            _cache[key] = _rows(
                conn, "SELECT * FROM silver WHERE pop_quarter = ? AND origin = 'us'", [repdte])
        else:
            path = _pop_snapshot_path(repdte, as_of)
            if path is None:
                _cache[key] = []
            else:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                _cache[key] = [to_bank_financials(r) for r in raw]
    return _cache[key]


def _eu_silver() -> list[dict]:
    """One Silver row per landed EBA bank, at its own latest available filing
    period, converted to USD. Empty list if EBA/FX haven't been landed (see
    scripts/land_eba.ps1) — the app degrades to US-only rather than crashing when
    this data is absent, same as footprints()/sod_raw() degrade when SOD isn't
    landed.

    EU periods don't line up with US REPDTEs (EBA publishes with its own lag,
    currently 2025Q2 vs a 2026Q1 US population) — each bank's own `quarter`/
    `filing_date` in the returned row is the honest source of truth for what's
    actually being shown, not the US repdte this function is indifferent to.
    """
    if "eu_silver" not in _cache:
        if not (_EBA_INSTITUTIONS.exists() and _EBA_FINANCIALS.exists() and _FX_EUR_USD.exists()):
            _cache["eu_silver"] = []
            return _cache["eu_silver"]
        institutions = {i["lei"]: i for i in
                        json.loads(_EBA_INSTITUTIONS.read_text(encoding="utf-8-sig"))}
        financials = json.loads(_EBA_FINANCIALS.read_text(encoding="utf-8-sig"))
        fx = json.loads(_FX_EUR_USD.read_text(encoding="utf-8-sig"))[0]
        # Optional (B2): the credit-risk cube (NPL + NACE sector concentration),
        # keyed the same (lei, period) way as `financials` — absent entirely on a
        # pre-B2 landing, same "degrade, don't crash" contract as EBA/FX above.
        credit_risk_by_key: dict[tuple[str, str], dict] = {}
        if _EBA_CREDIT_RISK.exists():
            for r in json.loads(_EBA_CREDIT_RISK.read_text(encoding="utf-8-sig")):
                credit_risk_by_key[(r["lei"], r["period"])] = r

        latest_by_lei: dict[str, dict] = {}
        for row in financials:
            lei = row["lei"]
            if lei not in latest_by_lei or row["period"] > latest_by_lei[lei]["period"]:
                latest_by_lei[lei] = row

        out = []
        for lei, row in latest_by_lei.items():
            inst = institutions.get(lei)
            if inst is None:          # a financials row with no matching institution row
                continue
            cr = credit_risk_by_key.get((lei, row["period"]))
            out.append(to_bank_financials_eba(row, inst, fx_rate=fx["rate"],
                                              fx_date=fx["date"], credit_risk=cr))
        _cache["eu_silver"] = out
    return _cache["eu_silver"]


def population(repdte: str | None = None, as_of: str | None = None,
               cluster_mode: str = "refit") -> dict:
    """Return {gold, by_cert, silver_by_cert, cluster_members, cluster_labels} for one
    quarter. Defaults to the most recent landed quarter, so every existing caller is
    unchanged.

    `cluster_mode` (C3, docs/audit/04-remediation-prompts.md):
      - "refit" (default, unchanged behavior) — k-means fit fresh on THIS
        quarter's population. `/clusters` keeps this as the real k-selection
        evidence surface (see `cluster_diagnostics`).
      - "fixed" — assign to centroids fit ONCE on a reference quarter and
        persisted by `cluster_centroids_cli` (`clustering.load_fixed_centroids`),
        so a boundary bank with a stable balance sheet gets the SAME cluster
        label across quarters instead of flipping on refit noise. Multi-quarter
        views (trends, briefing migrations) use this. Silently falls back to
        "refit" (with `cluster_mode` in the result reporting the fallback) if no
        fixed centroids have been persisted yet.

    Percentiles and clusters are computed WITHIN a quarter — a percentile against a
    pool mixing quarters would be meaningless. Real branch footprints (Feature 15's
    geo-overlap) are a separate cached accessor, see footprints().

    `as_of` (B9, docs/audit/04-remediation-prompts.md, YYYYMMDD): reproduce the
    numbers as they stood on that landing date rather than today's — FDIC
    restates prior quarters, and every re-land used to silently overwrite the
    prior snapshot, so a number shown today could differ from the same number
    shown last month with no way to prove which was "right" (both were, as of
    when they were served — see `_pop_snapshot_path`). Threads through every
    landed quarter this call touches (the requested quarter, its prior quarter
    for QoQ, and its own trailing history for growth_rate_3yr_pct), not just
    the headline one, so the whole response is internally consistent as of
    one date. `None` (the default everywhere) is today's unchanged behavior.
    """
    if cluster_mode not in ("refit", "fixed"):
        raise ValueError(f"cluster_mode must be 'refit' or 'fixed', got '{cluster_mode}'")
    repdte = repdte or latest_quarter()
    if repdte is None:
        raise FileNotFoundError(f"no landed population quarters under {_POP_DIR}")
    fixed = clustering.load_fixed_centroids() if cluster_mode == "fixed" else None
    effective_mode = "fixed" if fixed is not None else "refit"
    key = f"pop:{repdte}:{as_of or 'latest'}:{effective_mode}"
    if as_of is None:
        _note_pop_cache_use(repdte)   # the LRU only bounds the (unbounded-growth-risk) default path
    if key in _cache:                 # warm path: never touches the lock
        return _cache[key]
    with _cache_lock:
        # Double-checked: another thread may have filled this key (this exact
        # quarter/as_of/mode) while we were waiting for the lock -- without
        # this re-check, two concurrent cold requests for the SAME quarter
        # would both pay the full Gold/percentile/k-means computation below.
        if key in _cache:
            return _cache[key]
        _cache[key] = _compute_population(repdte, as_of, effective_mode, fixed)
    return _cache[key]


def _compute_population(repdte: str, as_of: str | None, effective_mode: str,
                        fixed: dict | None) -> dict:
    """The actual population() computation, called at most once per (repdte,
    as_of, effective_mode) — see population()'s cache-fill wrapper above,
    which holds `_cache_lock` for the duration of this call."""
    conn = _gold_conn()
    if conn is not None:
        if as_of is not None:
            raise ValueError(
                "as_of point-in-time queries need the JSON/Bronze path "
                "(BANKLENS_GOLD_DB unset) — the materialized DuckDB artifact "
                "only ever holds the latest landed snapshot of each quarter.")
        if effective_mode == "fixed":
            raise ValueError(
                "cluster_mode='fixed' needs the JSON/Bronze path (BANKLENS_GOLD_DB unset) — "
                "the materialized DuckDB artifact only ever bakes in per-quarter refit clusters "
                "(whatever population() computed at gold_db_cli.py build time).")
        # Every field population() would otherwise compute here — Gold
        # ratios, peer percentiles, behavioral cluster ids/labels — is
        # already baked into the materialized rows (gold_db_cli.py built
        # them by calling this exact function against the JSON/Bronze path
        # at build time), so this is two SELECTs and two GROUP BYs, not a
        # second computation of anything.
        gold_rows = [_unflatten_gold_row(r) for r in
                    _rows(conn, "SELECT * FROM gold WHERE pop_quarter = ?", [repdte])]
        silver_rows = _rows(conn, "SELECT * FROM silver WHERE pop_quarter = ?", [repdte])
        silver_by_cert = {r["cert_number"]: r for r in silver_rows if r.get("cert_number") is not None}
        cluster_members: dict[int, list] = defaultdict(list)
        cluster_labels: dict[int, str] = {}
        for g in gold_rows:
            cid = g.get("peer_cluster_id")
            if cid is not None:
                cluster_members[cid].append(g["cert_number"])
                cluster_labels[cid] = g.get("peer_cluster_label")
        return {
            "quarter": repdte, "gold": gold_rows,
            "by_cert": {g["cert_number"]: g for g in gold_rows},
            "silver_by_cert": silver_by_cert,
            "cluster_members": {cid: certs for cid, certs in cluster_members.items()},
            "cluster_labels": cluster_labels,
            "cluster_mode": "refit",
        }

    silver = _silver_for(repdte, as_of)
    # QoQ needs the same bank's prior quarter. Without this every qoq_* field is None,
    # which is exactly what the single-quarter landing used to produce for all 1,049.
    prev_q = previous_quarter(repdte)
    prev_by_cert = ({s.get("cert_number"): s for s in _silver_for(prev_q, as_of)}
                    if prev_q else {})
    # Trailing 3yr growth (growth_rate_3yr_pct / deposit_growth_rate_3yr_pct) needs
    # each bank's OWN history back to repdte-12q, newest-first starting with repdte
    # itself — see gold.growth_rate_nyr. Built once per repdte from the already-cached
    # per-quarter silver rows (_silver_for), not one bank_history() call per bank,
    # which would re-walk every landed quarter per bank instead of once per quarter.
    # Every quarter in this history is pinned to the SAME as_of, so a trailing
    # growth rate reproduced for a past date uses only data that existed by then.
    history_by_cert: dict[int, list[dict]] = defaultdict(list)
    for q in available_quarters():
        if q > repdte:
            continue
        for s in _silver_for(q, as_of):
            c = s.get("cert_number")
            if c is not None:
                history_by_cert[c].append(s)
    gold = [gold_features(s, prev_by_cert.get(s.get("cert_number")),
                          history_by_cert.get(s.get("cert_number")))
           for s in silver]

    # EU banks (EBA Transparency Exercise), if landed. No QoQ history landed yet for
    # EBA (only the latest period per bank), so prev=None — every qoq_* and
    # growth_rate_3yr_pct field is honestly None for these rows, not fabricated.
    eu_silver = _eu_silver()
    eu_gold = [gold_features(s) for s in eu_silver]

    # Percentiles ARE computed across the combined US+EU population now that EBA
    # amounts are converted to USD (see silver_eba.py) — but this mixes IFRS (EBA)
    # and US-GAAP (FDIC) accounting bases, and EU banks' filing period doesn't match
    # the US repdte. Directionally real, not a precise apples-to-apples rank.
    combined_gold = gold + eu_gold
    # C11: add_percentile_ranks' `_within_cluster` pass groups by
    # `peer_cluster_label` — that field isn't assigned until the clustering
    # block below runs, so this call MUST come after it (moved here from
    # right after `combined_gold` was built, which computed every
    # `_within_cluster` percentile as None for 100% of the population; live-
    # verified before this fix). `_within_size` doesn't have this dependency
    # (`asset_band` comes from gold_features, already set by this point) but
    # is computed in the same single pass regardless.

    silver_by_cert = {}
    for s, g in zip(silver, gold, strict=True):
        g["state"] = s.get("state")
        g["country"] = s.get("country")
        cert = s.get("cert_number")
        if cert is not None:
            silver_by_cert[cert] = s
    for s, g in zip(eu_silver, eu_gold, strict=True):
        g["state"] = s.get("state")         # always None — no EU equivalent
        g["country"] = s.get("country")
        g["lei"] = s.get("lei")
        cert = s.get("cert_number")
        if cert is not None:
            silver_by_cert[cert] = s

    # Behavioral clusters — US banks ONLY. EBA doesn't disclose the loan-mix/
    # deposit fields these clusters are built on (concentration_ratio_*,
    # uninsured_deposit_pct, core_deposit_pct); imputing them to the population
    # mean would silently place every EU bank in whichever cluster sits closest
    # to "average", a fabricated assignment. EU banks simply carry no
    # peer_cluster_id/label — see get_peer_cluster's handling of that.
    # Cluster IDs come from the label, not from k-means' arbitrary integer, so
    # the same behavioral group keeps the same id across quarters — otherwise a
    # multi-quarter view renders fake migration EVEN under refit mode.
    members: dict[int, list] = defaultdict(list)
    cluster_labels: dict[int, str] = {}
    if effective_mode == "fixed":
        # C3 — assign to centroids fit ONCE on `fixed["reference_quarter"]`
        # (cluster_centroids_cli), standardized against THAT fit's persisted
        # mu/sd, not this quarter's own — a genuinely fixed comparison, not
        # just a differently-seeded refit.
        kept, raw = clustering.build_raw_matrix(gold, fixed["features"])
        if raw:
            X = clustering.standardize_with(raw, fixed["mu"], fixed["sd"])
            labels = clustering.assign_fixed(X, fixed["centroids"])
            fixed_labels = {int(k): v for k, v in fixed["cluster_labels"].items()}
            for g, lab in zip(kept, labels, strict=True):
                sid = fixed["stable_ids"][lab]
                text = fixed_labels[sid]
                g["peer_cluster_id"] = sid
                g["peer_cluster_label"] = text
                cluster_labels[sid] = text
                members[sid].append(g)
    else:
        kept, X = clustering.build_matrix(gold)
        # An as_of (B9) predating this repdte's first-ever landing legitimately
        # returns zero rows (see _pop_snapshot_path) — a real, honest empty
        # result, not an error, but k-means has nothing to cluster in that case.
        raw_members = defaultdict(list)
        if X:
            labels, _, _ = clustering.kmeans(X, 7)
            for g, lab in zip(kept, labels, strict=True):
                raw_members[lab].append(g)
        for _lab, ms in raw_members.items():
            means = {m: _avg(ms, m) for m in _CLUSTER_METRICS}
            text = clustering.label_cluster(means)
            sid = clustering.stable_cluster_id(text)
            cluster_labels[sid] = text
            for g in ms:
                g["peer_cluster_id"] = sid
                g["peer_cluster_label"] = text
                members[sid].append(g)

    # C11 — after peer_cluster_label is assigned above, not before (see the
    # comment where this call used to sit, right after combined_gold's build).
    add_percentile_ranks(combined_gold)

    return {
        "quarter": repdte,
        "gold": combined_gold,
        "by_cert": {g["cert_number"]: g for g in combined_gold},
        "silver_by_cert": silver_by_cert,
        "cluster_mode": effective_mode,
        "cluster_members": {lab: [g["cert_number"] for g in ms] for lab, ms in members.items()},
        "cluster_labels": cluster_labels,
    }


def cluster_diagnostics(repdte: str | None = None) -> dict:
    """Feature 14 governance — silhouette + largest-cluster-share for k=2..7 on the
    SAME behavioral feature matrix `population()` clusters with, cached the same way.

    `population()` always serves k=7 (a fixed k is required for the stable-cluster-id
    scheme other pages depend on), but which k actually scores best on silhouette has
    only ever been visible via a CLI. This computes it once per quarter — 6 extra
    k-means runs (k=2..7, silhouette_by_k already reuses one `kmeans` call per k) is
    cheap at ~1k rows/7 features in pure Python, but still real work worth caching
    rather than repeating on every request.
    """
    repdte = repdte or latest_quarter()
    if repdte is None:
        raise FileNotFoundError(f"no landed population quarters under {_POP_DIR}")
    key = f"cluster_diag:{repdte}"
    if key in _cache:
        return _cache[key]
    pop = population(repdte)
    _, X = clustering.build_matrix(pop["gold"])
    diag = clustering.silhouette_by_k(X, k_range=range(2, 8))
    _cache[key] = {k: {"silhouette": v["silhouette"], "max_share": v["max_share"]}
                   for k, v in diag.items()}
    return _cache[key]


def bank_history(cert: int, as_of: str | None = None) -> list[dict]:
    """One bank's Silver rows across every landed population quarter, newest first.

    `bank_quarters()` below reads the per-bank `cert=<n>` Bronze partitions, which
    exist for only a handful of individually-landed banks. This reassembles the same
    shape from the population partitions instead, so multi-quarter analytics work for
    the whole population rather than those few certs.

    `as_of` (B9, YYYYMMDD): every quarter in the returned history is pinned to
    the Bronze snapshot as it stood on that date — see `population`'s
    docstring for why this needs to apply uniformly across the whole history,
    not just the latest quarter.
    """
    try:
        cert = int(cert)
    except (TypeError, ValueError):
        return []
    out = []
    for q in available_quarters():
        row = next((s for s in _silver_for(q, as_of) if s.get("cert_number") == cert), None)
        if row is not None:
            out.append(row)
    return out


def duckdb_gold() -> duckdb.DuckDBPyConnection:
    """A real DuckDB table over the computed Gold layer — the actual SQL query
    surface for query_banks() below, not ad hoc Python list filtering.

    When BANKLENS_GOLD_DB is set, this opens its own dedicated read-only
    connection to that artifact (see the "DEDICATED connection" comment below
    for why not the shared one) — no NDJSON round-trip at all, just a TEMP
    VIEW over the artifact's multi-quarter `gold` table filtered to the
    current latest quarter (population()'s own default scope, so
    query_banks() keeps searching "the current population", not every landed
    quarter at once). A TEMP VIEW lives in the connection's own in-memory
    catalog, not the read-only file, so it's created fresh per process
    without needing write access to the artifact.

    Otherwise (the JSON/Bronze path): population()'s Gold rows -> a scratch
    NDJSON file -> read_json_auto. Verified live that duckdb 1.5's Python API
    does NOT support scanning a plain list-of-dicts directly
    (`InvalidInputException: ... not suitable for replacement scans` — only
    DataFrame/Arrow/ndarray are), so the NDJSON round-trip is the robust
    option that doesn't require adding a pandas dependency just to get dict
    rows into a table. The scratch file is deleted immediately after loading;
    only the in-memory table persists (for the life of this cache entry, same
    as population()'s own cache).
    """
    if "duckdb_conn" in _cache:
        return _cache["duckdb_conn"]

    if _GOLD_DB:
        # A DEDICATED connection, deliberately NOT the shared _gold_conn()
        # every other accessor in this module reads through. Verified live:
        # creating a TEMP VIEW named "gold" on the shared connection silently
        # poisons every later bare `FROM gold` query on THAT SAME connection
        # (available_quarters(), population(), etc.) into hitting the
        # one-quarter view instead of the real multi-quarter table — DuckDB
        # resolves an unqualified name against the connection's own temp
        # catalog first. TEMP objects are connection-scoped, so a second
        # read-only connection to the same file gives query_banks() its own
        # "gold" name with zero risk of shadowing anyone else's queries.
        quarter = latest_quarter()
        assert quarter is not None and quarter.isdigit(), f"unexpected quarter value: {quarter!r}"
        conn = duckdb.connect(_GOLD_DB, read_only=True)
        # Even on its own connection, a bare `main.gold` is ambiguous: DuckDB's
        # temp catalog also has a schema named `main`, so an unqualified
        # `main.gold` two-part name matches both the artifact's real table AND
        # the temp view being created — verified live, it binds to itself
        # ("infinite recursion detected: attempting to recursively bind view
        # 'gold'"). The artifact's real catalog name is its filename (see
        # PRAGMA database_list), not "main", so it's looked up rather than
        # assumed, and the view references it three-part-qualified.
        (catalog,) = conn.execute("SELECT current_catalog()").fetchone()
        conn.execute(
            f'CREATE OR REPLACE TEMP VIEW gold AS SELECT * FROM "{catalog}".main.gold '
            f"WHERE pop_quarter = '{quarter}'")
        _cache["duckdb_conn"] = conn
        return conn

    gold = population()["gold"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ndjson", delete=False, encoding="utf-8"
    ) as f:
        for row in gold:
            f.write(json.dumps(row, default=str) + "\n")
        tmp_path = f.name
    try:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE gold AS SELECT * FROM read_json_auto(?)", [tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    _cache["duckdb_conn"] = con
    return con


def query_banks(query: str | None = None, state: str | None = None,
                country: str | None = None,
                min_assets_b: float | None = None, max_assets_b: float | None = None,
                limit: int = 20) -> list[dict]:
    """Filter/sort the Gold population via real SQL, replacing what used to be
    a hand-rolled Python list comprehension in tools.list_banks()."""
    con = duckdb_gold()
    clauses, params = [], []
    if query:
        clauses.append("lower(name) LIKE ?")
        params.append(f"%{query.lower()}%")
    if state:
        clauses.append("upper(state) = ?")
        params.append(state.upper())
    if country:
        clauses.append("upper(country) = ?")
        params.append(country.upper())
    if min_assets_b is not None:
        clauses.append("total_assets / 1e9 >= ?")
        params.append(min_assets_b)
    if max_assets_b is not None:
        clauses.append("total_assets / 1e9 <= ?")
        params.append(max_assets_b)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM gold {where} ORDER BY total_assets DESC NULLS LAST LIMIT ?"
    params.append(limit)
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def holdco_table() -> dict[int, dict]:
    """{rssd: holdco_row} for the latest landed Fed NIC FR Y-9C quarter (B4:
    docs/audit/04-remediation-prompts.md). Empty dict if fed_nic hasn't been
    landed (see scripts/land_fed_nic.ps1) — degrades the same way
    footprints()/sod_raw() do when their source is absent."""
    if "holdco_table" not in _cache:
        periods = sorted((p.name.split("=", 1)[1] for p in (_FED_NIC_DIR / "financials").glob("period=*")
                          if p.is_dir() and (p / "records.json").exists()), reverse=True) \
                 if (_FED_NIC_DIR / "financials").exists() else []
        if not periods or not _FED_NIC_ATTRS.exists():
            _cache["holdco_table"] = {}
        else:
            fin = json.loads((_FED_NIC_DIR / "financials" / f"period={periods[0]}" /
                              "records.json").read_text(encoding="utf-8-sig"))
            attrs = json.loads(_FED_NIC_ATTRS.read_text(encoding="utf-8-sig"))
            _cache["holdco_table"] = build_holdco_table(fin, attrs)
    return _cache["holdco_table"]


def holdco_parent_index() -> dict[int, int]:
    """{offspring_rssd: parent_rssd} from Fed NIC's landed relationships.
    Empty dict if not landed."""
    if "holdco_parent_index" not in _cache:
        if not _FED_NIC_RELATIONSHIPS.exists():
            _cache["holdco_parent_index"] = {}
        else:
            rels = json.loads(_FED_NIC_RELATIONSHIPS.read_text(encoding="utf-8-sig"))
            _cache["holdco_parent_index"] = build_parent_index(rels)
    return _cache["holdco_parent_index"]


def holding_company_for_cert(cert: int) -> dict | None:
    """This bank's holding company's consolidated Y-9C financials, or None if
    it has no separate holding company, Fed NIC hasn't been landed, or its
    holding company didn't file (recently merged, sub-$1B reporting
    exemption, etc — real, disclosed gaps, not fabricated zeros).

    Joins on RSSD, not name: FDIC's own `RSSDHCR` field (surfaced as
    `holding_company_rssd` by `silver.to_bank_financials`) IS the Fed NIC
    RSSD ID for this bank's holding company — see banklens_transforms.holdco's
    module docstring for why this needs no fuzzy matching, unlike the
    CERT<->CIK crosswalk.
    """
    silver = population()["silver_by_cert"].get(cert)
    rssd = silver.get("holding_company_rssd") if silver else None
    if rssd is None:
        return None
    return holdco_table().get(rssd)


def macro_series() -> dict[str, list[dict]]:
    """{series_id: [{date, value}, ...]} for every landed FRED series (B5:
    docs/audit/04-remediation-prompts.md — scripts/land_fred.ps1, needs the
    user's own free FRED_API_KEY). Empty dict if not landed, same degrade-
    don't-crash contract as footprints()/sod_raw()."""
    if "macro_series" not in _cache:
        out: dict[str, list[dict]] = {}
        if _FRED_DIR.exists():
            for part in sorted(_FRED_DIR.glob("series=*")):
                records_path = part / "records.json"
                if records_path.exists():
                    series_id = part.name.split("=", 1)[1]
                    out[series_id] = json.loads(records_path.read_text(encoding="utf-8-sig"))
        _cache["macro_series"] = out
    return _cache["macro_series"]


def sod_vintage() -> dict:
    """The landed SOD's real vintage — the survey year (from `_SOD`'s own
    partition path, not a second hardcoded copy of it) and when it was
    fetched (from the partition's `_provenance.json` sidecar, the same file
    every Bronze partition carries — see provenance.py). B7 (docs/audit/
    04-remediation-prompts.md): every branch-derived figure (footprints,
    county concentration, the branch map, M&A geo-overlap) is up to 18 months
    stale relative to a quarterly financial figure, since FDIC publishes SOD
    only annually — this makes that fact structural instead of one hardcoded
    `"as_of": "SOD 2025"` string on a single tool.

    `None` if SOD hasn't been landed at all (see scripts/land_sod.ps1)."""
    if "sod_vintage" not in _cache:
        if not _SOD.exists():
            _cache["sod_vintage"] = None
        else:
            year = _SOD.parent.name.split("=", 1)[1] if "=" in _SOD.parent.name else None
            prov_path = _SOD.parent / "_provenance.json"
            fetched_at = None
            if prov_path.exists():
                fetched_at = json.loads(prov_path.read_text(encoding="utf-8-sig")).get("fetched_at")
            _cache["sod_vintage"] = {"sod_year": int(year) if year else None, "fetched_at": fetched_at}
    return _cache["sod_vintage"]


def footprints() -> dict[int, dict]:
    """Real branch-level footprints keyed by CERT (bank-level, not holding-company —
    SOD branch data is per FDIC-insured bank, so no crosswalk needed here). Empty
    dict if SOD hasn't been landed (see scripts/land_sod.ps1), unless
    BANKLENS_GOLD_DB is set, in which case they're read back from the
    materialized `footprints` table instead of recomputed from raw SOD."""
    if "footprints" in _cache:
        return _cache["footprints"]
    conn = _gold_conn()
    if conn is not None:
        _cache["footprints"] = {r["cert_number"]: _footprint_from_row(r)
                                for r in _rows(conn, "SELECT * FROM footprints")}
    else:
        _cache["footprints"] = build_footprints(sod_raw())
    return _cache["footprints"]


# Territories with no boundary data landed in usTopology.ts's Albers-USA insets
# (which only cover the 50 states + DC) — these branches are excluded from the
# branch map and disclosed via excluded_non_contiguous. AK/HI ARE now included:
# us-atlas's states-albers-10m.json/counties-albers-10m.json ship real AK/HI
# insets built with the same geoAlbersUsa() convention branch points are
# projected through, so no boundary data is missing for them. See
# get_branch_map's docstring for the (much narrower) corrupt-coordinate filter
# that replaced the old blanket AK/HI exclusion.
NON_CONTIGUOUS_STATES = {"PR", "GU", "VI", "AS", "MP"}


def sod_raw() -> list[dict]:
    """Every landed SOD branch row, unfiltered — the full ~4,431-cert universe (every
    FDIC-insured bank), not just the $1B-$250B analytical slice. Market-share and
    branch-map both need the full universe: a share or HHI computed against only the
    population slice as denominator would overstate every number in it.

    When BANKLENS_GOLD_DB is set, reads the materialized `sod` table instead of
    the raw ~37MB Bronze JSON — same ~76k rows either way. (See A6 in
    docs/audit/04-remediation-prompts.md for making this lazy/per-state rather
    than loading the whole table into memory, which this function still does.)
    """
    if "sod_raw" not in _cache:
        conn = _gold_conn()
        if conn is not None:
            _cache["sod_raw"] = _rows(conn, "SELECT * FROM sod")
        else:
            _cache["sod_raw"] = json.loads(_SOD.read_text(encoding="utf-8-sig")) if _SOD.exists() else []
    return _cache["sod_raw"]


def county_table() -> dict[str, dict]:
    """{fips: county_deposit_table entry} over the FULL landed SOD — real input to
    Feature 15's county-level HHI, cached the same way population()'s clustering is.
    Read back from the materialized `county_table` when BANKLENS_GOLD_DB is set,
    rather than recomputed from raw SOD."""
    if "county_table" not in _cache:
        conn = _gold_conn()
        if conn is not None:
            _cache["county_table"] = {r["fips"]: _county_from_row(r)
                                      for r in _rows(conn, "SELECT * FROM county_table")}
        else:
            _cache["county_table"] = county_deposit_table(sod_raw())
    return _cache["county_table"]


def bank_name_by_cert() -> dict[int, str]:
    """Institution name for EVERY landed cert (not just the $1B-$250B population) —
    SOD's per-row NAMEBR is the BRANCH's own name (wrong for a multi-branch bank), but
    the BRNUM==0 row is FDIC's own head-office branch, whose NAMEBR is the institution's
    registered name. Verified live: all 4,431 landed certs carry a BRNUM==0 row."""
    if "bank_name_by_cert" not in _cache:
        _cache["bank_name_by_cert"] = {
            int(r["CERT"]): r.get("NAMEBR") for r in sod_raw()
            if r.get("BRNUM") == 0 and r.get("CERT") is not None
        }
    return _cache["bank_name_by_cert"]


def network_edges() -> dict[int, list[dict]]:
    """Feature 15 network view — each bank's top-3 M&A-fit partners, precomputed
    ONCE and cached rather than scored on the request path. Measured live at the
    original ~1,049-bank population: a full sweep (every bank ranked against
    the whole population, the real O(n^2) `fit_score` cost) took ~17s in pure
    Python — fine to pay once per quarter and cache (same pattern as
    population()'s own clustering step), but far too slow to repeat on every
    /network page load.

    NOT re-measured at the ~4,350-bank widened population (B3) — O(n^2) at ~4.1x
    the banks is ~17x the comparisons, so the true cold-cache cost here is on the
    order of minutes, not seconds, and may need F8's blocked/approximate
    nearest-neighbour search (docs/audit/04-remediation-prompts.md) before this
    is comfortable on a live first request rather than a warmed cache.
    """
    if "network_edges" in _cache:
        return _cache["network_edges"]
    pop = population()
    fps = footprints()
    edges = {
        g["cert_number"]: rank_partners(g, pop["gold"], top_n=3, footprints=fps)
        for g in pop["gold"]
    }
    _cache["network_edges"] = edges
    return edges


def bank_quarters(cert: int) -> list[dict] | None:
    """Per-bank multi-quarter Silver rows (newest-first), or None if not landed.

    SECURITY: `cert` reaches here as a raw MCP tool argument (via diff_filings) —
    the type hint says `int`, but nothing upstream actually enforces that, and the
    value is interpolated straight into a filesystem path. Verified live: a `cert`
    of "../../../../../.." reads records.json from OUTSIDE data/ entirely (a real,
    reachable path-traversal read). Coercing to a real int here closes it — a
    genuine FDIC CERT is always numeric, so anything else is rejected outright
    rather than silently path-joined.
    """
    try:
        cert = int(cert)
    except (TypeError, ValueError):
        return None
    p = DATA / "bronze" / "source=fdic" / f"cert={cert}" / "records.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    return [to_bank_financials(r) for r in raw]


def landed_bank_certs() -> list[int]:
    d = DATA / "bronze" / "source=fdic"
    return sorted(int(p.name.split("=")[1]) for p in d.glob("cert=*") if p.is_dir())


def _confident_crosswalk_by_rssd() -> dict:
    """{rssd: crosswalk_row} restricted to exact/high_confidence matches only
    (never a low-confidence guess) — the one crosswalk load every confident-
    match consumer in this module shares."""
    if "crosswalk_by_rssd" not in _cache:
        conn = _gold_conn()
        if conn is not None:
            rows = _rows(conn, "SELECT * FROM crosswalk")
        elif _CROSSWALK.exists():
            rows = json.loads(_CROSSWALK.read_text(encoding="utf-8"))
        else:
            rows = []
        _cache["crosswalk_by_rssd"] = {
            r["rssd"]: r for r in rows if r["match_type"] in ("exact", "high_confidence")
        }
    return _cache["crosswalk_by_rssd"]


def ticker_for_cert(cert: int) -> str | None:
    """The real, crosswalk-matched ticker for a bank's holding company (or its own
    ticker, for the banks with no separate holding company — see crosswalk.md),
    restricted to exact/high_confidence matches only (never a low-confidence guess)."""
    silver = population()["silver_by_cert"].get(cert)
    if not silver:
        return None
    rssd = silver.get("holding_company_rssd") or silver.get("rssd_id")
    row = _confident_crosswalk_by_rssd().get(rssd)
    return row["ticker"] if row else None


def filings_eligible_count() -> int:
    """How many landed-population banks have a confident (exact/high_confidence)
    CERT<->CIK crosswalk match — the real denominator for filings coverage (B8:
    docs/audit/04-remediation-prompts.md). Same eligibility rule
    `banklens_ingestion.filings_cli.eligible_banks` lands against, computed
    here from data this module already has cached rather than importing the
    ingestion package (mcp-server has no dependency on banklens_ingestion)."""
    confident_rssds = set(_confident_crosswalk_by_rssd())
    return sum(
        1 for s in population()["silver_by_cert"].values()
        if (s.get("holding_company_rssd") or s.get("rssd_id")) in confident_rssds
    )


def price_bars(ticker: str) -> list[dict] | None:
    """Landed EOD price bars for a ticker (ascending by date), or None if not landed
    (see scripts/land_market_data.ps1 — needs the user's own free Tiingo key).

    SECURITY (defense in depth): today `ticker` only ever arrives here via
    ticker_for_cert()'s trusted, crosswalk-derived value — never raw user input.
    But this function interpolates its argument into a filesystem path, exactly
    the shape that was a real, exploitable traversal in bank_quarters() (see that
    function's docstring). Rather than trust that no future call site changes,
    verify the resolved path is still inside the expected directory before
    reading — a check that holds regardless of what "valid ticker" turns out to
    mean, instead of guessing an allowed character set.
    """
    cache_key = f"bars:{ticker}"
    if cache_key in _cache:
        return _cache[cache_key]
    base = DATA / "bronze" / "source=tiingo" / "daily"
    p = base / f"ticker={ticker}" / "records.json"
    if base.resolve() not in p.resolve().parents:
        return None
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    bars = sorted((to_price_bar(r) for r in raw), key=lambda b: b["date"])
    _cache[cache_key] = bars
    return bars


def market_coverage() -> dict:
    """Real Tiingo landing coverage — how many crosswalk-matched tickers are
    actually landed vs eligible, and how stale the oldest one is. Written by
    market_cli.run() (see that module's docstring for the persisted cursor +
    hourly-budget scheme this reports on), not recomputed here — this is a
    read of that CLI's own coverage record, the same "compute once, read
    everywhere" contract the rest of this module follows.
    """
    p = DATA / "bronze" / "source=tiingo" / "_coverage.json"
    if not p.exists():
        return {"eligible": 0, "landed": 0, "coverage_pct": 0.0,
                "oldest_bar_age_days": None, "updated_at": None,
                "landed_yet": False}
    coverage = json.loads(p.read_text(encoding="utf-8"))
    coverage["landed_yet"] = True
    return coverage


# Each active source in config/sources.yaml, mapped to the glob(s) (relative
# to data/bronze/) where its own `_provenance.json` sidecars land. B10
# (docs/audit/04-remediation-prompts.md): provenance is captured on every
# landing already — this is the first thing that reads it back out instead of
# leaving it write-only. Several sources land into more than one partition
# shape (e.g. fdic_bankfind covers population AND the legacy per-cert lands);
# `data_freshness()` reports the MOST RECENTLY fetched one per source, since
# that's the honest answer to "how current is this source, right now".
_FRESHNESS_SOURCES: dict[str, list[str]] = {
    "fdic_bankfind": ["source=fdic/population/repdte=*/landed=*/_provenance.json",
                      "source=fdic/deposits/repdte=*/_provenance.json",
                      "source=fdic/cert=*/_provenance.json"],
    "fdic_sod": ["source=fdic/sod/year=*/_provenance.json"],
    "fdic_failures": ["source=fdic/failures/_provenance.json"],
    "sec_edgar": ["source=sec/tickers/_provenance.json", "source=sec/filings/cik=*/_provenance.json"],
    "fed_nic": ["source=fed_nic/attributes/_provenance.json",
               "source=fed_nic/relationships/_provenance.json",
               "source=fed_nic/financials/period=*/_provenance.json"],
    "fred": ["source=fred/series=*/_provenance.json"],
    "market_ohlc": ["source=tiingo/daily/ticker=*/_provenance.json"],
    "eba_transparency": ["source=eba/institutions/_provenance.json",
                         "source=eba/financials/_provenance.json",
                         "source=eba/credit_risk/_provenance.json"],
}

# How often each source is genuinely expected to publish a new vintage — the
# "expected next publication" B10 asks for is derived from this, not guessed
# per-request; None means "no fixed cadence to project from" (continuous/
# on-demand sources), stated honestly rather than inventing a schedule.
_SOURCE_CADENCE_DAYS: dict[str, int | None] = {
    "fdic_bankfind": 91, "fdic_sod": 365, "fdic_failures": None,
    "sec_edgar": None, "fed_nic": 91, "fred": None, "market_ohlc": 1,
    "eba_transparency": 182,
}


def data_freshness() -> dict:
    """Per-source landing vintage (B10): the most recently fetched Bronze
    partition's own `_provenance.json` — real timestamps this app already
    captures on every land, not a second hand-maintained "last updated" note
    that can drift from what was actually landed. A source with no landed
    data yet (still `status: planned`, or `status: active` but never run
    locally) reports `landed: False` rather than being omitted — the gap
    itself is the useful fact.
    """
    bronze = DATA / "bronze"
    out = {}
    for source_id, patterns in _FRESHNESS_SOURCES.items():
        newest: dict | None = None
        for pattern in patterns:
            for p in bronze.glob(pattern):
                try:
                    prov = json.loads(p.read_text(encoding="utf-8-sig"))
                except (json.JSONDecodeError, OSError):
                    continue
                if newest is None or (prov.get("fetched_at") or "") > (newest.get("fetched_at") or ""):
                    newest = prov
        cadence = _SOURCE_CADENCE_DAYS.get(source_id)
        expected_next = None
        if newest and newest.get("fetched_at") and cadence:
            from datetime import datetime, timedelta
            try:
                fetched = datetime.fromisoformat(newest["fetched_at"])
                expected_next = (fetched + timedelta(days=cadence)).date().isoformat()
            except ValueError:
                pass
        out[source_id] = {
            "landed": newest is not None,
            "fetched_at": newest.get("fetched_at") if newest else None,
            "endpoint": newest.get("endpoint") if newest else None,
            "record_count": newest.get("record_count") if newest else None,
            "expected_next_publication": expected_next,
        }
    return out


def population_provenance(repdte: str) -> dict | None:
    """G9: Bronze provenance for the FDIC population partition backing one landed
    REPDTE quarter — the exact `_provenance.json` written when that partition was
    landed (source URL, fetch timestamp, content checksum), same file format
    `data_freshness()` reads. `None` if the quarter was never landed or its
    partition has no `_provenance.json` (older/manually-placed partitions)."""
    snaps = _pop_snapshots(repdte)
    if not snaps:
        return None
    partition_dir = _POP_DIR / f"repdte={repdte}" / f"landed={snaps[-1]}"
    prov_path = partition_dir / "_provenance.json"
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    prov["partition_path"] = str(prov_path.relative_to(REPO)).replace("\\", "/")
    return prov


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0
