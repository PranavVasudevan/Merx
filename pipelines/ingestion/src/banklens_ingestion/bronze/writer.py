"""Land raw records into the Bronze layer as partitioned JSON + a provenance sidecar.

Layout (local dev): ``data/bronze/source=<src>/cert=<cert>/records.json`` with a
sibling ``_provenance.json``. In production this becomes an object-store path
backed by an Iceberg/Delta table, but the partitioning intent is identical.

Bronze is **append-only and immutable**: we never edit landed bytes, we re-land.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ..provenance import Provenance


def write_partition(records: list[dict], provenance: Provenance, *,
                    base_dir: Path, source: str, parts: Sequence[str]) -> Path:
    """Land into an arbitrary partition path, e.g. parts=("population", "repdte=20260331").

    The general form. `write_bronze` below is the cert-partitioned special case that
    predates it. Every landing path goes through here so a records.json can never be
    written without its provenance sidecar — the population and SOD CLIs used to write
    records directly and that's exactly how six partitions ended up with no provenance
    at all, and the 2026Q1 one ended up hand-authored with no checksum.
    """
    partition = base_dir / f"source={source}"
    for p in parts:
        partition = partition / p
    partition.mkdir(parents=True, exist_ok=True)

    records_path = partition / "records.json"
    records_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    (partition / "_provenance.json").write_text(
        json.dumps(provenance.to_dict(), indent=2), encoding="utf-8")
    return records_path


def write_bronze(records: list[dict], provenance: Provenance, *,
                 base_dir: Path, source: str, cert: int) -> Path:
    return write_partition(records, provenance, base_dir=base_dir, source=source,
                           parts=(f"cert={cert}",))
