"""A minimal MCP stdio client — spawns the BankLens MCP server as a subprocess and
speaks JSON-RPC 2.0 over its stdin/stdout, exactly as a real MCP-aware agent runtime
would. This is the ONLY way agents reach BankLens data: never a raw DB import.

Refactored out of scripts/mcp_demo.py so the agent framework and the demo share one
client implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]


class MCPStdioClient:
    """Context-managed client: `with MCPStdioClient() as c: c.list_tools()`."""

    def __init__(self, requester: str = "banklens-agent") -> None:
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._requester = requester

    def __enter__(self) -> "MCPStdioClient":
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([
            str(REPO / "services" / "mcp-server" / "src"),
            str(REPO / "pipelines" / "transforms" / "src"),
        ])
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "banklens_mcp.server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env=env, cwd=str(REPO),
        )
        # `clientInfo.name` is the MCP spec's standard place for a client to
        # identify itself at handshake time — the server threads it through to
        # every audit-log row for this connection (see server.py's `_audit`),
        # since a stdio server has no per-request auth header to read instead.
        self._send({"jsonrpc": "2.0", "id": self._id(), "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": self._requester, "version": "0.1.0"}}})
        self._recv()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc) -> None:
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    def _id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _send(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict:
        assert self._proc and self._proc.stdout
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        return json.loads(line)

    def list_tools(self) -> list[dict]:
        self._send({"jsonrpc": "2.0", "id": self._id(), "method": "tools/list"})
        return self._recv()["result"]["tools"]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool; returns its text content (JSON string on success)."""
        self._send({"jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
        resp = self._recv()
        result = resp.get("result", {})
        content = result.get("content", [{"text": json.dumps(resp)}])
        return content[0].get("text", "")
