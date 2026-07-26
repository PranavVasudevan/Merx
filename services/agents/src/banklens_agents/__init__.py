"""BankLens agentic AI layer (Phase 6) — Supervisor + specialist agents over MCP.

Agents are consumers of MCP tools, never of raw databases — every tool call goes
through the same governed, audited surface the UI and CLI use (services/mcp-server).

On import, ensure sibling packages are importable without requiring PYTHONPATH setup
for every entrypoint.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
for rel in ("pipelines/transforms/src", "services/mcp-server/src"):
    p = _ROOT / rel
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

__version__ = "0.1.0"
