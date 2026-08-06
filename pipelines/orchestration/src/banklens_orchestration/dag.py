"""A small, dependency-free DAG runner.

Every other layer of this repo (MCP server, clustering, logistic regression) is a
real, hand-rolled reference implementation rather than an early dependency on a
heavy framework — the ingestion/transforms `pyproject.toml` files say so explicitly
("Phase 1 is stdlib-only by design"). This module is the same choice applied to
orchestration: Airflow needs a metadata DB, webserver and scheduler process, and
Prefect's dependency tree alone is 60+ packages (fastapi, alembic, redis client,
docker SDK...) for what is, at this data volume, six sequential/branching Python
calls. What actually matters — topological ordering, retries, upstream-failure
short-circuiting, and a durable run log — fits in ~80 lines with no installs.

If pipeline count or team size outgrows this, the natural next step is exactly the
plan's Airflow/Prefect swap; `quarterly_refresh.py`'s `build_dag()` already returns
a plain dependency graph that maps directly onto either framework's task API.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import time
from collections.abc import Callable
from pathlib import Path


@dataclasses.dataclass
class Stage:
    name: str
    fn: Callable[[], None]
    depends_on: tuple[str, ...] = ()
    retries: int = 1
    retry_delay_s: float = 5.0


@dataclasses.dataclass
class StageResult:
    name: str
    ok: bool
    attempts: int
    duration_s: float
    error: str | None = None


def topological_order(stages: list[Stage]) -> list[Stage]:
    """Dependency-respecting order via DFS. Raises on an unknown dependency or a cycle
    — both are authoring bugs in the DAG definition, not runtime conditions to swallow."""
    by_name = {s.name: s for s in stages}
    for s in stages:
        for dep in s.depends_on:
            if dep not in by_name:
                raise ValueError(f"stage {s.name!r} depends on unknown stage {dep!r}")

    visited: set[str] = set()
    in_progress: set[str] = set()
    order: list[Stage] = []

    def visit(s: Stage) -> None:
        if s.name in visited:
            return
        if s.name in in_progress:
            raise ValueError(f"cycle detected at stage {s.name!r}")
        in_progress.add(s.name)
        for dep in s.depends_on:
            visit(by_name[dep])
        in_progress.discard(s.name)
        visited.add(s.name)
        order.append(s)

    for s in stages:
        visit(s)
    return order


def run_dag(stages: list[Stage], *, run_log: Path | None = None) -> list[StageResult]:
    """Run `stages` in dependency order. A stage that exhausts its retries fails, and
    every stage depending on it (directly or transitively) is skipped rather than run
    against upstream data that never landed — a bad Bronze pull must not silently feed
    a clustering run on stale Gold. Independent branches still run: an M&A/filings
    failure doesn't block the clustering branch that doesn't depend on it.
    """
    ordered = topological_order(stages)
    results: dict[str, StageResult] = {}
    failed: set[str] = set()

    for stage in ordered:
        blocked_by = [dep for dep in stage.depends_on if dep in failed]
        if blocked_by:
            results[stage.name] = StageResult(
                stage.name, False, 0, 0.0,
                error=f"skipped: upstream failure in {blocked_by}")
            failed.add(stage.name)
            continue

        attempts = 0
        last_err: str | None = None
        ok = False
        start = time.time()
        while attempts < max(stage.retries, 1):
            attempts += 1
            try:
                stage.fn()
                ok = True
                break
            except Exception as exc:  # a stage's own bug must not kill the whole DAG run
                last_err = f"{type(exc).__name__}: {exc}"
                if attempts < stage.retries:
                    time.sleep(stage.retry_delay_s)
        duration = time.time() - start
        results[stage.name] = StageResult(stage.name, ok, attempts, duration,
                                          error=None if ok else last_err)
        if not ok:
            failed.add(stage.name)

    ordered_results = [results[s.name] for s in ordered]
    if run_log is not None:
        run_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ok": not failed,
            "stages": [dataclasses.asdict(r) for r in ordered_results],
        }
        with open(run_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    return ordered_results
