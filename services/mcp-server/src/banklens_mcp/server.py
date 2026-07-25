"""BankLens MCP server — a dependency-free reference implementation.

Speaks the Model Context Protocol directly (JSON-RPC 2.0 over stdio, newline-delimited)
so it runs with zero installs and is fully inspectable. Production (Phase 5) swaps in
the official `mcp` SDK; the tool contracts in tools.py stay identical.

Handles: initialize, notifications/initialized, ping, tools/list, tools/call.
Every tool call is appended to data/mcp_audit.jsonl (the auditability requirement).

Run as an MCP server (configure an MCP client to launch it):
    $env:PYTHONPATH = "services/mcp-server/src;pipelines/transforms/src"
    python -m banklens_mcp.server
"""

from __future__ import annotations

import datetime
import json
import sys
import time

from . import data
from .tools import TOOLS, TOOL_BY_NAME

PROTOCOL_VERSION = "2025-06-18"
_AUDIT = data.DATA / "mcp_audit.jsonl"


def _result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _audit(tool, args, ok, ms):
    try:
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "tool": tool, "arguments": args, "ok": ok, "latency_ms": round(ms, 1)}
        with open(_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def handle(msg: dict):
    method = msg.get("method")
    mid = msg.get("id")

    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion", PROTOCOL_VERSION)
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
        start = time.time()
        try:
            out = tool["handler"](**args)
            _audit(name, args, True, (time.time() - start) * 1000)
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
