"""Shared OPA client — the one piece of code that knows how to ask
platform/auth/opa/policy.rego a yes/no question over HTTP.

Both services/api-gateway/src/auth.py (per-REST-route authorization) and
services/mcp-server/src/banklens_mcp/authz.py (per-MCP-tool authorization) call
`opa_query()` rather than each doing their own urllib POST — one real HTTP
mechanism against one real policy file, not two authorization systems that
happen to agree today and can silently drift apart tomorrow.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181/v1/data/banklens/allow")


class OpaUnavailable(Exception):
    """OPA couldn't be reached. Callers decide how to handle it: the REST
    bridge fails closed (503); the MCP server falls back to an in-process
    mirror of the same rules (see banklens_mcp.authz)."""


def opa_query(input_doc: dict, timeout: float = 3.0) -> bool:
    """POST {"input": input_doc} to OPA_URL and return its boolean `result`.
    Raises OpaUnavailable if OPA can't be reached at all (network/DNS/timeout)
    — a real deny decision from OPA itself still returns False normally,
    that's not this exception."""
    body = json.dumps({"input": input_doc}).encode()
    req = urllib.request.Request(
        OPA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
    except (OSError, urllib.error.URLError) as e:
        raise OpaUnavailable(f"could not reach OPA at {OPA_URL}: {e}") from e
    return bool(result.get("result"))
