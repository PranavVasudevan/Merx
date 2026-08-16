"""F20 — catches the specific class of drift that made README.md wrong before
this phase: a number or schedule stated in prose that quietly stopped
matching the code (the MCP tool count; "data refreshes are not scheduled"
after `platform/k8s/base/refresh-cronjob.yaml` started existing), and a
repository-layout tree or script reference pointing at something that no
longer exists.

Deliberately NOT a full README fact-checker (there is no such thing) — four
specific, mechanically-verifiable claims, each checked against the real
source it claims to describe:

  1. Every directory named in the fenced repository-layout tree exists.
  2. Every `scripts/*.ps1` referenced in the "Getting started" block exists.
  3. The MCP tool count README states matches `len(banklens_mcp.tools.TOOLS)`.
  4. The CronJob schedule README describes matches
     `platform/k8s/base/refresh-cronjob.yaml`'s real `schedule:` field.

Run: ``python scripts/check_readme_claims.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"

for rel in ("services/mcp-server/src", "pipelines/transforms/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


_TREE_LINE = re.compile(r"^((?:│   |    )*)(?:├── |└── )(\S+)")


def _tree_paths(readme_text: str) -> list[Path]:
    """Walks the tree block maintaining a directory stack keyed by depth, so
    a nested entry like "│   ├── ingestion/" resolves to "pipelines/ingestion",
    not just "ingestion". The root "banklens/" line has no branch marker
    (│/├/└) at all and is skipped — it names the repo root itself, not a
    subdirectory to check for existence."""
    m = re.search(r"## Repository layout\s*\n```\n(.*?)\n```", readme_text, re.DOTALL)
    if not m:
        return []
    stack: dict[int, str] = {}
    paths = []
    for line in m.group(1).splitlines():
        branch_m = _TREE_LINE.match(line)
        if not branch_m:
            continue
        indent, name = branch_m.groups()
        if not name.endswith("/"):
            continue
        depth = len(indent) // 4
        stack[depth] = name.rstrip("/")
        parts = [stack[d] for d in sorted(stack) if d <= depth]
        paths.append(Path(*parts))
    return paths


def check_scripts_referenced(readme_text: str) -> list[str]:
    errors = []
    for m in re.finditer(r"scripts/([A-Za-z0-9_.-]+\.ps1)", readme_text):
        script = REPO / "scripts" / m.group(1)
        if not script.exists():
            errors.append(f"README references scripts/{m.group(1)}, which does not exist")
    return errors


def check_mcp_tool_count(readme_text: str) -> list[str]:
    m = re.search(r"(\d+) tools over the Gold layer", readme_text)
    if not m:
        return ["could not find the MCP tool-count claim "
                "('<N> tools over the Gold layer') in README.md"]
    claimed = int(m.group(1))
    try:
        from banklens_mcp.tools import TOOLS
    except Exception as e:
        return [f"could not import banklens_mcp.tools to verify the tool count: {e}"]
    actual = len(TOOLS)
    if claimed != actual:
        return [f"README claims {claimed} MCP tools; banklens_mcp.tools.TOOLS actually "
                f"has {actual}"]
    return []


def check_cronjob_schedule(readme_text: str) -> list[str]:
    cronjob_path = REPO / "platform" / "k8s" / "base" / "refresh-cronjob.yaml"
    if not cronjob_path.exists():
        # If a future refactor removes the CronJob, README claiming a
        # scheduled refresh would itself be the drift — but that's the same
        # "path exists" class scripts/check_doc_references.py already covers
        # for `platform/k8s/base/refresh-cronjob.yaml` mentions in README, so
        # nothing further to check here in that case.
        return []
    schedule_m = re.search(r'schedule:\s*"([^"]+)"', cronjob_path.read_text(encoding="utf-8"))
    if not schedule_m:
        return [f"could not find a `schedule:` field in {cronjob_path.relative_to(REPO)}"]
    cron = schedule_m.group(1)
    # "0 6 5 2,5,8,11 *" -> 06:00 UTC on the 5th of Feb/May/Aug/Nov. Rather
    # than parse cron syntax generically (overkill for one field), just
    # assert the specific numbers this cron expression encodes are the same
    # ones spelled out in prose in the README, so the two can't silently
    # diverge if either is edited alone.
    minute, hour, day, months, _dow = cron.split()
    month_names = {"2": "February", "5": "May", "8": "August", "11": "November"}
    expected_months = [month_names[m] for m in months.split(",") if m in month_names]
    errors = []
    if f"{int(hour):02d}:{int(minute):02d} UTC" not in readme_text:
        errors.append(f"README's stated refresh time doesn't match the CronJob's real "
                      f"schedule ('{cron}' -> {int(hour):02d}:{int(minute):02d} UTC)")
    if f"{day}th of" not in readme_text:
        errors.append(f"README's stated refresh day doesn't match the CronJob's real "
                      f"schedule ('{cron}' -> day {day})")
    for month in expected_months:
        if month not in readme_text:
            errors.append(f"README doesn't mention '{month}', but the CronJob schedule "
                          f"('{cron}') includes it")
    return errors


def main() -> int:
    if not README.exists():
        print("ERROR: README.md not found.")
        return 1
    text = README.read_text(encoding="utf-8")

    errors: list[str] = []
    for path in _tree_paths(text):
        if not (REPO / path).is_dir():
            errors.append(f"repository-layout tree lists '{path.as_posix()}/', "
                          "which does not exist")
    errors += check_scripts_referenced(text)
    errors += check_mcp_tool_count(text)
    errors += check_cronjob_schedule(text)

    if errors:
        print(f"FAIL: {len(errors)} README claim(s) no longer hold:\n")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: every checked README claim matches the current code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
