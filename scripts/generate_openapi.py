"""F19 — regenerate docs/api/openapi.json from bridge_server.py's own route
tables (see services/api-gateway/src/openapi_spec.py's module docstring for
what this does and does not model).

    python scripts/generate_openapi.py           # writes docs/api/openapi.json
    python scripts/generate_openapi.py --check    # exits 1 if the committed
                                                    # file would change (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "docs" / "api" / "openapi.json"

for rel in ("services/api-gateway/src", "services/mcp-server/src",
            "pipelines/transforms/src", "services/agents/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def render() -> str:
    import auth
    import bridge_server
    import openapi_spec

    spec = openapi_spec.build_openapi_spec(
        get_routes=bridge_server.ROUTES, post_routes=bridge_server.POST_ROUTES,
        delete_routes=bridge_server.DELETE_ROUTES, route_tiers=bridge_server.ROUTE_TIERS,
        open_routes=auth.OPEN_ROUTES, version="0.1.0")
    return json.dumps(spec, indent=2, sort_keys=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if docs/api/openapi.json is stale, without writing it")
    args = ap.parse_args()

    rendered = render()

    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else None
        if current == rendered:
            print(f"OK: {OUT_PATH.relative_to(REPO)} is in sync with the bridge's route tables.")
            return 0
        print(f"STALE: {OUT_PATH.relative_to(REPO)} does not match what "
              "bridge_server.py's ROUTES/POST_ROUTES/DELETE_ROUTES/ROUTE_TIERS "
              "currently generate. Run `python scripts/generate_openapi.py` and commit the result.")
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
