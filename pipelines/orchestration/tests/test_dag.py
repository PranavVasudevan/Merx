"""Orchestration DAG runner — ordering, retries, and upstream-failure short-circuit.
Pure Python, no network and no landed data.

Run: ``python pipelines/orchestration/tests/test_dag.py``  (no pytest needed)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_orchestration.dag import Stage, run_dag, topological_order  # noqa: E402


def test_topological_order_respects_dependencies():
    stages = [
        Stage("c", lambda: None, depends_on=("a", "b")),
        Stage("a", lambda: None),
        Stage("b", lambda: None, depends_on=("a",)),
    ]
    names = [s.name for s in topological_order(stages)]
    assert names.index("a") < names.index("b") < names.index("c")


def test_unknown_dependency_and_cycle_are_authoring_errors():
    for stages, expect in (
        ([Stage("x", lambda: None, depends_on=("ghost",))], "ghost"),
        ([Stage("a", lambda: None, depends_on=("b",)),
          Stage("b", lambda: None, depends_on=("a",))], "cycle"),
    ):
        try:
            topological_order(stages)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert expect in str(e)


def test_run_dag_runs_dependencies_before_dependents():
    order: list[str] = []
    run_dag([
        Stage("land", lambda: order.append("land")),
        Stage("crosswalk", lambda: order.append("crosswalk"), depends_on=("land",)),
        Stage("cluster", lambda: order.append("cluster"), depends_on=("land",)),
    ])
    assert order[0] == "land" and set(order[1:]) == {"crosswalk", "cluster"}


def test_transient_failure_is_retried():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")

    res = run_dag([Stage("flaky", flaky, retries=3, retry_delay_s=0)])
    assert res[0].ok and res[0].attempts == 2


def test_downstream_is_skipped_but_independent_branches_still_run():
    """A failed Bronze pull must not feed a clustering run on stale data — but it
    also must not block work that never depended on it."""
    ran: list[str] = []
    res = run_dag([
        Stage("land", lambda: (_ for _ in ()).throw(RuntimeError("pull failed")), retries=1),
        Stage("crosswalk", lambda: ran.append("crosswalk"), depends_on=("land",)),
        Stage("independent", lambda: ran.append("independent")),
    ])
    by_name = {r.name: r for r in res}
    assert not by_name["land"].ok
    assert not by_name["crosswalk"].ok and "skipped" in by_name["crosswalk"].error
    assert "crosswalk" not in ran                 # never actually invoked
    assert by_name["independent"].ok and "independent" in ran


def test_repo_root_resolves_to_the_actual_repo_root():
    """Regression: quarterly_refresh.py computed REPO with parents[3], which is
    `pipelines/`, not the repo root — so --data-dir defaulted to
    `<repo>/pipelines/data`. Invisible locally (the .ps1 wrapper sets PYTHONPATH
    itself, masking the bad sys.path entry) and only surfaced when run in a
    container, where it died on PermissionError. Anchor it to a file that genuinely
    only exists at the repo root."""
    from banklens_orchestration.quarterly_refresh import REPO
    assert (REPO / "pipelines").is_dir(), f"REPO resolved to {REPO}"
    assert (REPO / "scripts").is_dir(), f"REPO resolved to {REPO}"
    assert REPO.name != "pipelines"


def test_run_log_is_durable_and_records_each_stage():
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "runs" / "quarterly_refresh.jsonl"
        run_dag([Stage("only", lambda: None)], run_log=log)
        record = json.loads(log.read_text(encoding="utf-8").strip())
        assert record["ok"] is True
        assert record["stages"][0]["name"] == "only"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} test(s) failed"))
    sys.exit(1 if failures else 0)
