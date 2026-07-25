"""BankLens MCP server (Phase 5) — the governed tool surface.

Thin orchestration: tools validate + audit, then call the feature logic in
banklens_transforms. See docs/api/mcp-tools.md.

On import, ensure the transforms package is importable without requiring the caller
to set PYTHONPATH for it (an MCP client only needs this package on the path).
"""

import sys
from pathlib import Path

_TRANSFORMS = Path(__file__).resolve().parents[4] / "pipelines" / "transforms" / "src"
if _TRANSFORMS.is_dir() and str(_TRANSFORMS) not in sys.path:
    sys.path.insert(0, str(_TRANSFORMS))

__version__ = "0.1.0"
