"""Data access for the MCP tools — loads the landed Bronze, builds the Gold
feature layer + peer percentiles + behavioral clusters once, and caches it.

The MCP server is thin: it reads the SAME Gold/feature logic the CLI and (later)
the UI use. No business logic lives here that isn't already in banklens_transforms.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path

import duckdb

from banklens_transforms import clustering
from banklens_transforms.footprint import build_footprints
from banklens_transforms.gold import gold_features
from banklens_transforms.market import to_price_bar
from banklens_transforms.peers import add_percentile_ranks
from banklens_transforms.silver import to_bank_financials

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"
_POP_DIR = DATA / "bronze" / "source=fdic" / "population"
_CROSSWALK = DATA / "silver" / "crosswalk.json"
_SOD = DATA / "bronze" / "source=fdic" / "sod" / "year=2025" / "records.json"

_CLUSTER_METRICS = ["concentration_ratio_cre", "concentration_ratio_c_and_i",
                    "concentration_ratio_residential_mortgage", "uninsured_deposit_pct",
                    "core_deposit_pct"]
# The training-only historical cross-sections. They carry a REDUCED 15-field set
# (landed for the deposit-flight model, not for analytics) so they must never be
# picked up as "the current quarter" or as a QoQ comparison base.
_TRAINING_ONLY_QUARTERS = {"20221231", "20080331"}

_cache: dict = {}


def available_quarters() -> list[str]:
    """Landed analytical population quarters, newest first (REPDTE strings).

    Discovered by glob rather than hardcoded — this used to pin `repdte=20260331`,
    which made every multi-quarter view impossible.
    """
    if "quarters" not in _cache:
        found = sorted((p.name.split("=", 1)[1] for p in _POP_DIR.glob("repdte=*")
                        if p.is_dir() and (p / "records.json").exists()), reverse=True)
        _cache["quarters"] = [q for q in found if q not in _TRAINING_ONLY_QUARTERS]
    return _cache["quarters"]


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


def _silver_for(repdte: str) -> list[dict]:
    key = f"silver:{repdte}"
    if key not in _cache:
        path = _POP_DIR / f"repdte={repdte}" / "records.json"
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        _cache[key] = [to_bank_financials(r) for r in raw]
    return _cache[key]


def population(repdte: str | None = None) -> dict:
    """Return {gold, by_cert, silver_by_cert, cluster_members, cluster_labels} for one
    quarter. Defaults to the most recent landed quarter, so every existing caller is
    unchanged.

    Percentiles and clusters are computed WITHIN a quarter — a percentile against a
    pool mixing quarters would be meaningless. Real branch footprints (Feature 15's
    geo-overlap) are a separate cached accessor, see footprints().
    """
    repdte = repdte or latest_quarter()
    if repdte is None:
        raise FileNotFoundError(f"no landed population quarters under {_POP_DIR}")
    key = f"pop:{repdte}"
    if key in _cache:
        return _cache[key]

    silver = _silver_for(repdte)
    # QoQ needs the same bank's prior quarter. Without this every qoq_* field is None,
    # which is exactly what the single-quarter landing used to produce for all 1,049.
    prev_q = previous_quarter(repdte)
    prev_by_cert = ({s.get("cert_number"): s for s in _silver_for(prev_q)}
                    if prev_q else {})
    gold = [gold_features(s, prev_by_cert.get(s.get("cert_number"))) for s in silver]
    add_percentile_ranks(gold)

    silver_by_cert = {}
    for s, g in zip(silver, gold, strict=True):
        g["state"] = s.get("state")
        cert = s.get("cert_number")
        if cert is not None:
            silver_by_cert[cert] = s

    # Behavioral clusters (k=7, deterministic seed). Cluster IDs come from the label,
    # not from k-means' arbitrary integer, so the same behavioral group keeps the same
    # id across quarters — otherwise a multi-quarter view renders fake migration.
    kept, X = clustering.build_matrix(gold)
    labels, _, _ = clustering.kmeans(X, 7)
    raw_members = defaultdict(list)
    for g, lab in zip(kept, labels, strict=True):
        raw_members[lab].append(g)

    members: dict[int, list] = defaultdict(list)
    cluster_labels: dict[int, str] = {}
    for lab, ms in raw_members.items():
        means = {m: _avg(ms, m) for m in _CLUSTER_METRICS}
        text = clustering.label_cluster(means)
        sid = clustering.stable_cluster_id(text)
        cluster_labels[sid] = text
        for g in ms:
            g["peer_cluster_id"] = sid
            g["peer_cluster_label"] = text
            members[sid].append(g)

    _cache[key] = {
        "quarter": repdte,
        "gold": gold,
        "by_cert": {g["cert_number"]: g for g in gold},
        "silver_by_cert": silver_by_cert,
        "cluster_members": {lab: [g["cert_number"] for g in ms] for lab, ms in members.items()},
        "cluster_labels": cluster_labels,
    }
    return _cache[key]


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


def bank_history(cert: int) -> list[dict]:
    """One bank's Silver rows across every landed population quarter, newest first.

    `bank_quarters()` below reads the per-bank `cert=<n>` Bronze partitions, which
    exist for only a handful of individually-landed banks. This reassembles the same
    shape from the population partitions instead, so multi-quarter analytics work for
    the whole population rather than those few certs.
    """
    try:
        cert = int(cert)
    except (TypeError, ValueError):
        return []
    out = []
    for q in available_quarters():
        row = next((s for s in _silver_for(q) if s.get("cert_number") == cert), None)
        if row is not None:
            out.append(row)
    return out


def duckdb_gold() -> duckdb.DuckDBPyConnection:
    """A real DuckDB table over the computed Gold layer — the actual SQL query
    surface for query_banks() below, not ad hoc Python list filtering.

    Loading path: population()'s Gold rows -> a scratch NDJSON file ->
    read_json_auto. Verified live that duckdb 1.5's Python API does NOT support
    scanning a plain list-of-dicts directly (`InvalidInputException: ... not
    suitable for replacement scans` — only DataFrame/Arrow/ndarray are), so the
    NDJSON round-trip is the robust option that doesn't require adding a pandas
    dependency just to get dict rows into a table. The scratch file is deleted
    immediately after loading; only the in-memory table persists (for the life
    of this cache entry, same as population()'s own cache).
    """
    if "duckdb_conn" in _cache:
        return _cache["duckdb_conn"]
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


def footprints() -> dict[int, dict]:
    """Real branch-level footprints keyed by CERT (bank-level, not holding-company —
    SOD branch data is per FDIC-insured bank, so no crosswalk needed here). Empty
    dict if SOD hasn't been landed (see scripts/land_sod.ps1)."""
    if "footprints" in _cache:
        return _cache["footprints"]
    if not _SOD.exists():
        _cache["footprints"] = {}
    else:
        raw = json.loads(_SOD.read_text(encoding="utf-8-sig"))
        _cache["footprints"] = build_footprints(raw)
    return _cache["footprints"]


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


def ticker_for_cert(cert: int) -> str | None:
    """The real, crosswalk-matched ticker for a bank's holding company (or its own
    ticker, for the banks with no separate holding company — see crosswalk.md),
    restricted to exact/high_confidence matches only (never a low-confidence guess)."""
    if "crosswalk_by_rssd" not in _cache:
        if not _CROSSWALK.exists():
            _cache["crosswalk_by_rssd"] = {}
        else:
            rows = json.loads(_CROSSWALK.read_text(encoding="utf-8"))
            _cache["crosswalk_by_rssd"] = {
                r["rssd"]: r for r in rows if r["match_type"] in ("exact", "high_confidence")
            }
    silver = population()["silver_by_cert"].get(cert)
    if not silver:
        return None
    rssd = silver.get("holding_company_rssd") or silver.get("rssd_id")
    row = _cache["crosswalk_by_rssd"].get(rssd)
    return row["ticker"] if row else None


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


def _avg(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0
