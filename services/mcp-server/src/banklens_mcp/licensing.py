"""Loads config/sources.yaml once at import and enforces `license.redistributable`
at the MCP serving boundary — the mechanism that file's own header claims exists
(G3: docs/audit/04-remediation-prompts.md). No YAML dependency: mcp-server ships
with zero installs (see server.py's module docstring, and this repo has no
PyYAML dependency anywhere), so this reads only the handful of scalar fields the
registry actually needs out of `sources.yaml`'s own block structure, rather than
pulling in a general YAML parser for one file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SOURCES_YAML = REPO / "config" / "sources.yaml"

_KEY_RE = re.compile(r"^  ([A-Za-z0-9_]+):\s*$")       # top-level "  <source_id>:" lines
_REDIST_RE = re.compile(r"redistributable:\s*(true|false)", re.IGNORECASE)
_TAG_RE = re.compile(r"\btag:\s*([A-Za-z0-9_.-]+)")
_NAME_RE = re.compile(r'name:\s*"([^"]*)"')


def _load_sources(path: Path) -> dict[str, dict]:
    """A minimal reader for THIS file's specific shape (one top-level `sources:`
    mapping, each entry keyed at 2-space indent) — not a general YAML parser.
    A source with no parseable `redistributable` value fails CLOSED (treated as
    non-redistributable): a registry typo or format drift must never silently
    open a licensing hole. Returns {} (same fail-closed effect, via
    is_redistributable's `.get`) if the file itself is missing or unreadable.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    try:
        start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "sources:") + 1
    except StopIteration:
        return {}

    out: dict[str, dict] = {}
    current_id: str | None = None
    block: list[str] = []

    def flush() -> None:
        if current_id is None:
            return
        text = "\n".join(block)
        redist = _REDIST_RE.search(text)
        tag = _TAG_RE.search(text)
        name = _NAME_RE.search(text)
        out[current_id] = {
            "name": name.group(1) if name else current_id,
            "license_tag": tag.group(1) if tag else None,
            "redistributable": bool(redist and redist.group(1).lower() == "true"),
        }

    for line in lines[start:]:
        if line and not line.startswith(" "):
            break   # dedented back to column 0 — past the `sources:` block entirely
        key = _KEY_RE.match(line)
        if key:
            flush()
            current_id, block = key.group(1), []
        else:
            block.append(line)
    flush()
    return out


SOURCES: dict[str, dict] = _load_sources(SOURCES_YAML)


def is_redistributable(source_id: str) -> bool:
    """Fails CLOSED: an unregistered source_id is treated as non-redistributable,
    never assumed safe just because it isn't in the registry."""
    src = SOURCES.get(source_id)
    return bool(src and src.get("redistributable"))


# Tool/Gold field name -> config/sources.yaml source id, for every field this
# server can serve that originates from a licensed (non-keyless) upstream. Only
# Tiingo (`market_ohlc`) is non-redistributable today (see sources.yaml) — a
# future licensed addition only needs one entry here, not a bespoke check at
# every call site that happens to touch it. Mirrors market.py's
# to_price_bar/price_snapshot field lists.
#
# Deliberately does NOT include "ticker": the ticker symbol itself comes from
# BankLens's own CERT<->CIK/RSSD crosswalk (data.ticker_for_cert), not from
# Tiingo's feed — only the OHLCV values Tiingo actually licenses are tagged.
FIELD_SOURCES: dict[str, str] = {
    "open": "market_ohlc", "high": "market_ohlc",
    "low": "market_ohlc", "close": "market_ohlc", "volume": "market_ohlc",
    "adj_close": "market_ohlc", "adj_volume": "market_ohlc",
    "div_cash": "market_ohlc", "split_factor": "market_ohlc",
    "change_1d_pct": "market_ohlc", "volatility_30d_pct": "market_ohlc",
    "week52_high": "market_ohlc", "week52_low": "market_ohlc",
    "bars": "market_ohlc",
}


class NonRedistributableError(ValueError):
    """A response would put non-redistributable-source data into a bulk
    (more-than-one-entity) context."""


def assert_bulk_allowed(source_id: str, entity_count: int, *, tool: str) -> None:
    """The actual enforcement point config/sources.yaml's header claims exists.

    `entity_count` is the number of distinct banks a response is about to cover,
    supplied by the caller (never guessed here — only the caller knows what it's
    about to return). <=1 is display (one bank, however much history) and always
    passes; >1 is a bulk/redistribution shape, blocked unless the registry marks
    `source_id` redistributable.
    """
    if entity_count <= 1 or is_redistributable(source_id):
        return
    src = SOURCES.get(source_id, {})
    raise NonRedistributableError(
        f"{tool}: {src.get('name', source_id)} data (source '{source_id}', license "
        f"'{src.get('license_tag', 'unknown')}') is registered redistributable=false "
        f"in config/sources.yaml and cannot be served for {entity_count} banks in one "
        f"response — single-bank display is unaffected."
    )


def bulk_blocked(source_id: str, entity_count: int) -> bool:
    """Same test as `assert_bulk_allowed`, as a bool instead of a raise — for a
    caller (get_market_overview) that wants to keep serving the rest of a bulk
    response and only omit the non-redistributable part of it."""
    return entity_count > 1 and not is_redistributable(source_id)


def assert_fields_bulk_allowed(field_names, entity_count: int, *, tool: str) -> None:
    """Same boundary check as `assert_bulk_allowed`, for tools (like compare_banks,
    or a curated multi-bank projection) where the field list — not a single fixed
    source — determines whether non-redistributable data is in play."""
    if entity_count <= 1:
        return
    for source_id in {FIELD_SOURCES[f] for f in field_names if f in FIELD_SOURCES}:
        assert_bulk_allowed(source_id, entity_count, tool=tool)
