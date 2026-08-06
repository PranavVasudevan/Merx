"""DAG runner tests — ordering, retries, upstream-failure short-circuit. All pure
Python/stdlib, no network and no landed data.

Run: ``python pipelines/orchestration/tests/test_dag.py``  (no pytest needed)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_orchestration.dag import Stage, run_dag, topological_order  # noqa: E402


def test_topological_order_respects_dependencies():
    calls: list[str] = []
    stages = [
        Stage("c", lambda: calls.append("c"), depends_on=("a", "b")),
        Stage("a", lambda: calls.append("a")),
        Stage("b", lambda: calls.append("b"), depends_on=("a",)),
    ]
    ordered = topological_order(stages)
    names = [s.name for s in ordered]
    assert names.index("a") < names.index("b") < names.index("c")


def test_topological_order_rejects_unknown_dependency():
    try:
        topological_order([Stage("x", lambda: None, depends_on=("ghost",))])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "ghost" in str(e)


def test_topological_order_rejects_cycle():
    try:
        topological_order([
            Stage("a", lambda: None, depends_on=("b",)),
            Stage("b", lambda: None, depends_on=("a",)),
        ])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "cycle" in str(e)


def test_run_dag_all_succeed_in_order():
    order: list[str] = []
    stages = [
        Stage("land", lambda: order.append("land")),
        Stage("crosswalk", lambda: order.append("crosswalk"), depends_on=("land",)),
        Stage("cluster", lambda: order.append("cluster"), depends_on=("land",)),
    ]
    results = run_dag(stages)
    assert order.index("land") < order.index("crosswalk")
    assert order.index("land") < order.index("cluster")
    assert all(r.ok for r in results)


def test_run_dag_retries_before_succeeding():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")

    results = run_dag([Stage("flaky", flaky, retries=3, retry_delay_s=0)])
    assert results[0].ok
    assert results[0].attempts == 2


def test_run_dag_skips_downstream_of_a_failed_stage():
    ran: list[str] = []
    stages = [
        Stage("land", lambda: (_ for _ in ()).throw(RuntimeError("bronze pull failed")),
              retries=1),
        Stage("crosswalk", lambda: ran.append("crosswalk"), depends_on=("land",)),
        Stage("independent", lambda: ran.append("independent")),
    ]
    results = run_dag(stages)
    by_name = {r.name: r for r in results}
    assert not by_name["land"].ok
    assert not by_name["crosswalk"].ok
    assert "skipped" in by_name["crosswalk"].error
    assert "crosswalk" not in ran               # never actually invoked
    assert by_name["independent"].ok             # unrelated branch still runs
    assert "independent" in ran


def test_run_dag_writes_a_durable_run_log():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "runs" / "quarterly_refresh.jsonl"
        run_dag([Stage("only", lambda: None)], run_log=log_path)
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        import json
        record = json.loads(lines[0])
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
