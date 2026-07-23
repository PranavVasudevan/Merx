"""Provenance metadata attached to every Bronze record set.

Auditability is a first-class requirement (this is a bank). Every raw landing
carries where it came from, when, and a content checksum so re-runs are
idempotent and any downstream number is traceable to its source bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


def sha256_of(payload: object) -> str:
    """Stable SHA-256 of a JSON-serialisable payload (sorted keys)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Provenance:
    """Immutable record of one fetch, landed alongside the raw data."""

    source: str            # e.g. "fdic.bankfind"
    endpoint: str          # the URL actually called
    license: str           # license tag from the source registry
    fetched_at: str        # ISO-8601 UTC
    record_count: int
    checksum: str          # sha256 of the raw payload

    @staticmethod
    def create(source: str, endpoint: str, license: str, payload: object) -> "Provenance":
        return Provenance(
            source=source,
            endpoint=endpoint,
            license=license,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            record_count=len(payload) if isinstance(payload, (list, tuple)) else 1,
            checksum=sha256_of(payload),
        )

    def to_dict(self) -> dict:
        return asdict(self)
