"""BankLens MCP server — a dependency-free reference implementation.

Speaks the Model Context Protocol directly (JSON-RPC 2.0 over stdio, newline-delimited)
so it runs with zero installs and is fully inspectable. Production (Phase 5) swaps in
the official `mcp` SDK; the tool contracts in tools.py stay identical.

Handles: initialize, notifications/initialized, ping, tools/list, tools/call.
Every tool call is logged to the real `mcp_audit_log` Postgres table (see
libs/python/banklens_common/src/banklens_common/db.py — needs
`docker compose -f platform/docker/docker-compose.dev.yml up -d postgres`).
If Postgres is unreachable, falls back to appending data/mcp_audit.jsonl so a
quick local run without Docker running doesn't lose its audit trail entirely,
but warns once per process rather than failing silently.

Run as an MCP server (configure an MCP client to launch it):
    $env:PYTHONPATH = "services/mcp-server/src;pipelines/transforms/src"
    python -m banklens_mcp.server
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from typing import Callable, cast

from banklens_common import db as common_db

from . import data
from .authz import authorize_tool
from .tools import TOOLS, TOOL_BY_NAME

PROTOCOL_VERSION = "2025-06-18"
_AUDIT = data.DATA / "mcp_audit.jsonl"
_pg_warned = False
# Set from `initialize`'s clientInfo.name (MCP spec) — the closest thing a
# stdio server has to a caller identity, since there's no per-request auth
# header the way an HTTP server would have. One process serves one client
# connection, so this is safe to hold as module state rather than threading
# it through every call.
_requester = "unknown"
# Set from `initialize`'s params.roles — the MCP spec has no standard field
# for this (stdio has no per-request auth header to carry it, same reason
# _requester exists), so a client asserts its caller's roles once at session
# setup, same lifecycle as clientInfo. Defaults to no roles at all, not
# ["viewer"]: a client that never declares roles gets every tool denied
# rather than silently granted viewer-tier access.
_roles: list[str] = []


def _result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _coerce_arguments(args: dict, schema: dict) -> dict:
    """Coerce loosely-typed JSON-RPC arguments (e.g. '"6976"' where the schema
    says integer) to match the declared inputSchema. Real clients send this —
    caught live from a local Ollama model that emitted {"cert": "6976"} for an
    integer-typed param, which then failed a dict lookup keyed by real ints with
    a misleading "not found" error instead of an obvious type error. Best-effort:
    a value that can't be coerced is passed through unchanged (the handler's own
    validation/lookup will raise a clear error rather than this coercion masking one).
    """
    props = (schema or {}).get("properties", {})
    out = dict(args)
    for key, value in args.items():
        prop = props.get(key)
        if not prop or value is None:
            continue
        want = prop.get("type")
        if want == "integer" and not isinstance(value, int):
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                pass
        elif want == "number" and not isinstance(value, (int, float)):
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                pass
        elif want == "array":
            items = value if isinstance(value, list) else [value]  # lone scalar -> singleton list
            item_type = prop.get("items", {}).get("type")
            if item_type == "integer":
                coerced = []
                for v in items:
                    try:
                        coerced.append(v if isinstance(v, int) else int(v))
                    except (TypeError, ValueError):
                        coerced.append(v)
                items = coerced
            out[key] = items
    return out


def _audit(tool, args, ok, ms):
    global _pg_warned
    ts = datetime.datetime.now(datetime.timezone.utc)
    try:
        common_db.record_audit(tool, args, ok, ms, ts=ts, requester=_requester)
        return
    except Exception as exc:
        if not _pg_warned:
            print(f"[banklens_mcp] Postgres audit log unavailable ({exc}); "
                  f"falling back to {_AUDIT} for this process", file=sys.stderr)
            _pg_warned = True
    try:
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": ts.isoformat(), "tool": tool, "arguments": args, "ok": ok,
               "latency_ms": round(ms, 1), "requester": _requester}
        with open(_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def handle(msg: dict):
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        global _requester, _roles
        params = msg.get("params") or {}
        proto = params.get("protocolVersion", PROTOCOL_VERSION)
        client_name = (params.get("clientInfo") or {}).get("name")
        if client_name:
            _requester = str(client_name)
        roles = params.get("roles")
        if isinstance(roles, list):
            _roles = [str(r) for r in roles]
        return _result(mid, {
            "protocolVersion": proto,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "banklens", "version": "0.1.0"},
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None                          # notifications: no response
    if method == "ping":
        return _result(mid, {})
    if method == "tools/list":
        return _result(mid, {"tools": [
            {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
            for t in TOOLS]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOL_BY_NAME.get(name)
        if tool is None:
            return _error(mid, -32602, f"unknown tool: {name}")
        # TOOL_BY_NAME.get(name) only returns non-None for a real key it was
        # actually built from, which means `name` was a real string (TOOLS'
        # own "name" fields) -- true by construction, but TOOL_BY_NAME's
        # values are dicts with deliberately heterogeneous value types
        # (str/dict/callable per entry, see tools.py's TOOLS registry), so
        # mypy can only infer `name`/`tool["handler"]`/`tool["inputSchema"]`
        # as broad unions from that mix, not their real per-key types.
        assert isinstance(name, str)
        start = time.time()
        try:
            # Authorization runs before coercion/execution — an unauthorized call
            # shouldn't pay for (or leak anything through timing of) argument
            # handling or the handler itself. Still inside this same try: a denial
            # is an in-band tool error (isError: true), not a raised exception that
            # would kill the process for every other in-flight call — same
            # "malformed input can't crash the server" contract the coercion
            # comment below already established for bad arguments.
            authorize_tool(name, _roles)
            # Coercion lives INSIDE the try: a malformed, non-dict `arguments` value
            # (e.g. a client sending a bare string instead of an object — not valid
            # per the protocol, but a client shouldn't be able to crash the whole
            # server subprocess over it) must become an in-band tool error, not an
            # uncaught exception that kills the process for every other in-flight call.
            coerced = _coerce_arguments(args, cast(dict, tool["inputSchema"]))
            handler = cast(Callable[..., dict], tool["handler"])
            out = handler(**coerced)
            _audit(name, coerced, True, (time.time() - start) * 1000)
            return _result(mid, {"content": [
                {"type": "text", "text": json.dumps(out, indent=2, default=str)}]})
        except Exception as exc:  # tool errors are returned in-band per MCP
            _audit(name, args, False, (time.time() - start) * 1000)
            return _result(mid, {"content": [{"type": "text", "text": f"error: {exc}"}],
                                 "isError": True})

    if mid is not None:
        return _error(mid, -32601, f"method not found: {method}")
    return None


def main() -> None:
    data.population()          # warm the cache before serving
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
