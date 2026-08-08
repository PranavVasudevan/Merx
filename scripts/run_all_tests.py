"""Run every BankLens test file and report an aggregate result.

Each test file is self-contained with its own stdlib runner (no pytest needed), so
this discovers them and runs each as a subprocess — one crashing file can't take
down the rest, and the per-file exit code is the source of truth.

Tests that need landed Bronze data (`data/`, git-ignored and reproducible from the
landing scripts) SKIP rather than fail when it's absent, so this is safe to run on
a fresh clone or in CI.

    python scripts/run_all_tests.py
    python scripts/run_all_tests.py --quiet     # summary only
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Same PYTHONPATH the individual scripts/*.ps1 wrappers set up. banklens_common
# isn't here — it's a real editable pip install (`pip install -e
# libs/python/banklens_common`), not a PYTHONPATH-only package like the rest.
SRC_PATHS = [
    REPO / "services" / "agents" / "src",
    REPO / "services" / "mcp-server" / "src",
    REPO / "pipelines" / "transforms" / "src",
    REPO / "pipelines" / "ingestion" / "src",
    REPO / "pipelines" / "orchestration" / "src",
]

SEARCH_DIRS = [REPO / "pipelines", REPO / "services", REPO / "libs"]

_COUNT_RE = re.compile(r"^(PASS|FAIL|SKIP|ERROR)\s", re.MULTILINE)


def discover() -> list[Path]:
    found: list[Path] = []
    for d in SEARCH_DIRS:
        found.extend(sorted(d.rglob("test_*.py")))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Run all BankLens tests")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    args = ap.parse_args()

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in SRC_PATHS)

    files = discover()
    if not files:
        # Discovering nothing is a FAILURE, not a pass. Without this, deleting or
        # mis-locating every test file turns CI green — the suite reports
        # "0 files | 0 passed | 0 failed" and exits 0, which reads identically to
        # a healthy run. An empty suite verifies nothing and must say so loudly.
        print(f"ERROR: no test files discovered under "
              f"{', '.join(str(d.relative_to(REPO)) for d in SEARCH_DIRS)}.")
        print("       Either tests are missing/misplaced, or this step should be "
              "removed from CI: an empty suite must not report success.")
        return 1

    totals = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}
    failed_files: list[str] = []

    for f in files:
        proc = subprocess.run([sys.executable, str(f)], capture_output=True,
                              text=True, env=env, cwd=str(REPO))
        out = proc.stdout + proc.stderr
        counts = {k: 0 for k in totals}
        for kind in _COUNT_RE.findall(out):
            counts[kind] += 1
            totals[kind] += 1

        rel = f.relative_to(REPO).as_posix()
        ok = proc.returncode == 0
        if not ok:
            failed_files.append(rel)

        if not args.quiet:
            status = "OK  " if ok else "FAIL"
            bits = f"{counts['PASS']} passed"
            if counts["SKIP"]:
                bits += f", {counts['SKIP']} skipped"
            if counts["FAIL"] or counts["ERROR"]:
                bits += f", {counts['FAIL'] + counts['ERROR']} failed"
            print(f"{status}  {rel:<58} {bits}")
            # Surface the actual failure lines — a silent red X helps nobody.
            if not ok:
                for line in out.splitlines():
                    if line.startswith(("FAIL", "ERROR")):
                        print(f"        {line}")

    print("\n" + "=" * 72)
    print(f"  {len(files)} files | {totals['PASS']} passed | "
          f"{totals['SKIP']} skipped | {totals['FAIL'] + totals['ERROR']} failed")
    if failed_files:
        print(f"  failing files: {', '.join(failed_files)}")
    print("=" * 72)
    return 1 if failed_files else 0


if __name__ == "__main__":
    sys.exit(main())
