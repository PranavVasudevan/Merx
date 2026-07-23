"""Land raw records into the Bronze layer as partitioned JSON + a provenance sidecar.

Layout (local dev): ``data/bronze/source=<src>/cert=<cert>/records.json`` with a
sibling ``_provenance.json``. In production this becomes an object-store path
backed by an Iceberg/Delta table, but the partitioning intent is identical.

Bronze is **append-only and immutable**: we never edit landed bytes, we re-land.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..provenance import Provenance


def write_bronze(records: list[dict], provenance: Provenance, *,
                 base_dir: Path, source: str, cert: int) -> Path:
    partition = base_dir / f"source={source}" / f"cert={cert}"
    partition.mkdir(parents=True, exist_ok=True)

    records_path = partition / "records.json"
    prov_path = partition / "_provenance.json"

    records_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    prov_path.write_text(json.dumps(provenance.to_dict(), indent=2), encoding="utf-8")
    return records_path
