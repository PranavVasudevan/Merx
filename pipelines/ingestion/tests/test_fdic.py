"""Unit tests for the FDIC connector that do NOT hit the network.

We test the pure parts (envelope unwrapping, field selection). A live smoke test
against the real API is kept separate and opt-in so CI stays hermetic.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_ingestion.sources.fdic import FdicSource  # noqa: E402


def test_unwrap_envelope():
    payload = {"data": [{"data": {"CERT": 3511, "ASSET": 1}, "score": {}},
                        {"data": {"CERT": 3511, "ASSET": 2}, "score": {}}]}
    rows = FdicSource._unwrap(payload)
    assert rows == [{"CERT": 3511, "ASSET": 1}, {"CERT": 3511, "ASSET": 2}]


def test_unwrap_empty():
    assert FdicSource._unwrap({"data": []}) == []


def test_source_metadata():
    s = FdicSource()
    assert s.name == "fdic.bankfind"
    assert s.license == "public-domain-us-gov"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} failed"))
    sys.exit(1 if failures else 0)
