"""Materialize the Gold layer into a single queryable DuckDB artifact.

Free-hosting reality: the REST bridge currently reads ~96MB of Bronze JSON from
a `data/` directory mounted read-only into its container (see
`banklens_mcp/data.py`) — no free host persists an ephemeral disk like that.
This CLI computes the SAME Gold layer, branch footprints, county deposit
table, crosswalk and behavioral-cluster assignments `banklens_mcp.data`
computes at runtime — by calling the exact same functions
(`data.population()`, `data.footprints()`, `data.county_table()`,
`data.sod_raw()`), not reimplementing them — and writes the result into one
DuckDB file. Point `BANKLENS_GOLD_DB` at that file and `banklens_mcp/data.py`
loads from it directly, with no Bronze JSON present at all (see that module's
`_GOLD_DB` branch).

Every table also gets a `provenance` table: the source URL, fetch timestamp
and content checksum of every Bronze partition that was read to build this
artifact — the artifact is derived data, but it should still be possible to
answer "where did this number ultimately come from" without the Bronze JSON
sitting next to it.

Cluster assignments are NOT a separate table: `peer_cluster_id`/
`peer_cluster_label` are already columns on every US gold row (computed by
`population()`'s own k-means step), so the loader in data.py reconstructs
`cluster_members`/`cluster_labels` with two GROUP BYs instead of re-running
k-means against a DuckDB-loaded matrix — one clustering computation, same as
everywhere else in this codebase ("build Gold once, reuse everywhere").

Run:
    python -m banklens_transforms.gold_db_cli
    python -m banklens_transforms.gold_db_cli --out data/banklens_gold.duckdb
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[4]
for rel in ("services/mcp-server/src", "pipelines/transforms/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_mcp import data  # noqa: E402
from banklens_transforms import footprint  # noqa: E402

DEFAULT_OUT = REPO / "data" / "banklens_gold.duckdb"

# The only Gold fields that are ever a nested dict rather than a scalar (see
# gold.qoq_delta) — DuckDB's read_json_auto would otherwise infer a STRUCT
# column for these two and leave every other field alone, which is an
# unnecessary type-inference risk to carry when a plain JSON-text column
# round-trips through duckdb's Python API exactly as reliably as a string
# always has. data.py's loader reverses this (_unflatten_gold_row).
_NESTED_GOLD_FIELDS = ("qoq_total_deposits", "qoq_uninsured_deposit_pct")


def _flatten_gold_row(g: dict) -> dict:
    out = dict(g)
    for k in _NESTED_GOLD_FIELDS:
        if out.get(k) is not None:
            out[k] = json.dumps(out[k])
    return out


def _footprint_to_row(cert: int, fp: dict) -> dict:
    centroid = fp.get("centroid")
    return {
        "cert_number": cert, "branch_count": fp["branch_count"],
        "total_deposits": fp["total_deposits"],
        "centroid_lat": centroid[0] if centroid else None,
        "centroid_lon": centroid[1] if centroid else None,
        "geo_basis": fp["geo_basis"],
        "states_json": json.dumps(sorted(fp["states"])),
        "counties_json": json.dumps(sorted(fp["counties"])),
        "cells_json": json.dumps([footprint.encode_cell(c) for c in fp["cells"]]),
        "deposits_by_cell_json": json.dumps(
            {footprint.encode_cell(k): v for k, v in fp["deposits_by_cell"].items()}),
    }


def _county_to_row(fips: str, entry: dict) -> dict:
    return {
        "fips": fips, "name": entry.get("name"), "state": entry.get("state"),
        "total_deposits": entry.get("total_deposits", 0.0),
        "branch_count": entry.get("branch_count", 0),
        "by_cert_json": json.dumps({str(k): v for k, v in entry.get("by_cert", {}).items()}),
    }


def _provenance_rows(data_dir: Path) -> list[dict]:
    """Every landed `_provenance.json` under data/bronze/ — the source URL,
    fetch timestamp and checksum for each Bronze partition read to build this
    artifact, so the derived DuckDB file carries the same lineage discipline
    Bronze itself does rather than stopping at Bronze."""
    rows = []
    for p in sorted((data_dir / "bronze").rglob("_provenance.json")):
        try:
            prov = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append({
            "partition": str(p.parent.relative_to(data_dir)).replace("\\", "/"),
            "source": prov.get("source"), "fetched_at": prov.get("fetched_at"),
            "checksum": prov.get("checksum"), "endpoint": prov.get("endpoint"),
        })
    return rows


def _write_table(con: duckdb.DuckDBPyConnection, name: str, rows: list[dict]) -> None:
    """NDJSON round-trip into a real DuckDB table — the same technique
    data.duckdb_gold() already uses at runtime for the same reason noted
    there: duckdb 1.5's Python API doesn't support scanning a plain
    list-of-dicts directly (verified live), only DataFrame/Arrow/ndarray, and
    a temp-file round trip is the option that doesn't add a pandas
    dependency just to get dict rows into a table. This is a one-time
    offline build step, not a hot runtime path, so the round trip's cost is
    irrelevant here (unlike the runtime one A6 removes)."""
    if not rows:
        print(f"  (skipping empty table: {name})")
        return
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ndjson", delete=False, encoding="utf-8"
    ) as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
        tmp_path = f.name
    try:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_json_auto(?)", [tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    (n,) = con.execute(f"SELECT count(*) FROM {name}").fetchone()
    print(f"  {name}: {n} rows")


def build(out_path: Path) -> None:
    # Always <repo>/data — banklens_mcp.data's own DATA constant is fixed at
    # import time from ITS file location, so a --data-dir override here
    # couldn't actually redirect what data.population()/footprints()/etc.
    # read; making that flag look configurable would be a lie.
    data_dir = data.DATA
    quarters = data.available_quarters()
    if not quarters:
        raise SystemExit(
            f"no landed population quarters under {data_dir}/bronze/source=fdic/population — "
            "run scripts/land_population.ps1 first")

    print(f"Materializing {len(quarters)} landed quarter(s) from {data_dir}...")
    gold_rows: list[dict] = []
    silver_rows: list[dict] = []
    for q in quarters:
        pop = data.population(q)
        for g in pop["gold"]:
            row = _flatten_gold_row(g)
            row["pop_quarter"] = q   # which population(repdte) request this row belongs to —
            row["origin"] = "us" if g.get("country") == "US" else "eu"
            gold_rows.append(row)    # distinct from EU rows' own `quarter` field, see module docstring
        for s in pop["silver_by_cert"].values():
            row = dict(s)
            row["pop_quarter"] = q
            # US-only vs EU-unioned-into-every-quarter — data.py's DB-backed
            # _silver_for() filters on this to reproduce the JSON path's
            # US-only semantics exactly (bank_history() depends on it: EU
            # certs currently return no history, since EBA lands only the
            # latest period per bank, and that must stay true either way).
            row["origin"] = "us" if s.get("country") == "US" else "eu"
            silver_rows.append(row)
        print(f"  {q}: {len(pop['gold'])} gold rows, {len(pop['silver_by_cert'])} silver rows "
              f"(incl. EU banks, unioned into every quarter same as population() does live)")

    footprint_rows = [_footprint_to_row(cert, fp) for cert, fp in data.footprints().items()]
    county_rows = [_county_to_row(fips, entry) for fips, entry in data.county_table().items()]
    sod_rows = data.sod_raw()
    crosswalk_path = data_dir / "silver" / "crosswalk.json"
    crosswalk_rows = (json.loads(crosswalk_path.read_text(encoding="utf-8"))
                      if crosswalk_path.exists() else [])
    prov_rows = _provenance_rows(data_dir)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    con = duckdb.connect(str(out_path))
    print("Writing tables...")
    _write_table(con, "gold", gold_rows)
    _write_table(con, "silver", silver_rows)
    _write_table(con, "footprints", footprint_rows)
    _write_table(con, "county_table", county_rows)
    _write_table(con, "sod", sod_rows)
    _write_table(con, "crosswalk", crosswalk_rows)
    _write_table(con, "provenance", prov_rows)
    con.close()

    size_mb = out_path.stat().st_size / 1e6
    print(f"\nWrote {out_path} ({size_mb:.1f} MB)")
    if size_mb > 50:
        print(f"WARNING: artifact is {size_mb:.1f} MB, over the 50 MB free-tier target.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Materialize the Gold layer (+footprints/county/crosswalk/clusters) "
                    "into one DuckDB artifact for BANKLENS_GOLD_DB.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"output DuckDB file path (default {DEFAULT_OUT})")
    args = p.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
