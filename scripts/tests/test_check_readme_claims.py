"""Tests for scripts/check_readme_claims.py (F20). Exercises the checker
against small synthetic README text (not the real README.md, so these stay
correct even as README.md's prose evolves) plus one live end-to-end run
against the real file as a smoke test.

Run: ``python scripts/tests/test_check_readme_claims.py``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import check_readme_claims as crc  # noqa: E402

_TREE_BLOCK = """## Repository layout

```
banklens/
├── config/          Environment configuration
├── pipelines/
│   ├── ingestion/     Bronze-layer connectors
│   └── transforms/    Silver and Gold layer derivations
└── scripts/         PowerShell entry points
```
"""


def test_tree_paths_resolves_nested_entries_relative_to_their_parent():
    paths = crc._tree_paths(_TREE_BLOCK)
    assert Path("config") in paths
    assert Path("pipelines") in paths
    assert Path("pipelines", "ingestion") in paths
    assert Path("pipelines", "transforms") in paths
    assert Path("scripts") in paths


def test_tree_paths_does_not_include_the_root_banklens_line_itself():
    paths = crc._tree_paths(_TREE_BLOCK)
    assert Path("banklens") not in paths


def test_check_scripts_referenced_flags_a_missing_script():
    text = "run `scripts/this_script_does_not_exist_xyz.ps1` to do the thing"
    errors = crc.check_scripts_referenced(text)
    assert len(errors) == 1
    assert "this_script_does_not_exist_xyz.ps1" in errors[0]


def test_check_scripts_referenced_passes_for_a_real_script():
    text = "run `scripts/run_orchestrator.ps1` to refresh"
    assert crc.check_scripts_referenced(text) == []


def test_check_mcp_tool_count_flags_a_wrong_number():
    from banklens_mcp.tools import TOOLS
    wrong = len(TOOLS) + 1
    errors = crc.check_mcp_tool_count(f"the surface exposes {wrong} tools over the Gold layer")
    assert len(errors) == 1
    assert str(wrong) in errors[0]


def test_check_mcp_tool_count_passes_for_the_real_count():
    from banklens_mcp.tools import TOOLS
    text = f"the surface exposes {len(TOOLS)} tools over the Gold layer"
    assert crc.check_mcp_tool_count(text) == []


def test_check_cronjob_schedule_flags_a_wrong_time_of_day():
    # The real CronJob fires at 06:00 UTC — a README claiming a different
    # time must be flagged.
    text = "runs at 09:00 UTC on the 5th of February, May, August and November"
    errors = crc.check_cronjob_schedule(text)
    assert any("time" in e for e in errors)


def test_check_cronjob_schedule_flags_a_missing_month():
    text = "runs at 06:00 UTC on the 5th of February, May and August"  # November missing
    errors = crc.check_cronjob_schedule(text)
    assert any("November" in e for e in errors)


def test_check_cronjob_schedule_passes_for_the_real_schedule():
    text = ("runs at 06:00 UTC on the 5th of February, May, August and November")
    assert crc.check_cronjob_schedule(text) == []


def test_end_to_end_against_the_real_readme_currently_passes():
    """Smoke test, not a synthetic-input unit test: the real README.md, as
    committed, must pass every check right now (this IS F20's acceptance
    test) — a failure here means a real, uncommitted drift, not a test bug."""
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "check_readme_claims.py")],
                            capture_output=True, text=True, cwd=str(REPO))
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {e!r}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
