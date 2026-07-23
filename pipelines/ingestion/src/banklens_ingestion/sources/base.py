"""The connector contract.

Every data source (FDIC, FFIEC, SEC EDGAR, Fed NIC, FRED, market data) implements
this same shape: ``discover -> fetch -> (checksum, land)``. The base class also
carries the *license tag*, which the platform later enforces at the serving /
MCP boundary (open govt data vs. licensed market data).
"""

from __future__ import annotations

import abc
from typing import Any


class Source(abc.ABC):
    """Abstract base for a Bronze-layer connector."""

    #: short stable id, e.g. "fdic.bankfind"
    name: str = "unknown"
    #: license tag from config/sources.yaml, e.g. "public-domain-us-gov"
    license: str = "unspecified"

    @abc.abstractmethod
    def fetch(self, *args: Any, **kwargs: Any) -> list[dict]:
        """Return a list of raw records (untouched source shape)."""
        raise NotImplementedError
