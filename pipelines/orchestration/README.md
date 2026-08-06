# orchestration

Wires the manual `pipelines/ingestion/src/banklens_ingestion/*_cli.py` scripts into
one scheduled DAG: `land_population -> crosswalk -> {market_data, filings}` and
`land_population -> {clustering, deposit_flight_retrain}`, with per-stage retries
and upstream-failure short-circuiting (a failed Bronze pull skips the crosswalk
that depends on it, but the independent clustering branch still runs).

This replaces the earlier `pipelines/dagster/` placeholder. It is deliberately
**not** Dagster/Airflow/Prefect: every other layer of this repo is a real,
dependency-free reference implementation before reaching for a heavy framework
(the MCP server hand-rolls JSON-RPC instead of installing the `mcp` SDK; peer
clustering and the deposit-flight classifier are hand-rolled instead of
scikit-learn/XGBoost) — see each module's docstring for the stated rationale.
`dag.py` is that same choice for orchestration: topological ordering, retries and
a durable JSONL run log in ~120 lines, no installs. See `dag.py`'s docstring for
the full argument and the explicit upgrade path if this repo ever needs a real
scheduler daemon, a UI, or cross-machine execution — `quarterly_refresh.build_dag()`
already returns a plain list of `Stage(name, fn, depends_on, retries)`, the same
shape either framework's task API expects, so porting it is mechanical.

## Running

```
powershell -File scripts/run_orchestrator.ps1
powershell -File scripts/run_orchestrator.ps1 -Repdte 20260630 -LandSod -SodYear 2026
```

Each run appends one JSON record to `data/orchestration_runs/quarterly_refresh.jsonl`
(timestamp, overall ok/fail, and per-stage attempts/duration/error) — enough to
answer "did last quarter's refresh actually run" without a dashboard.

## Real scheduling

This module runs one DAG invocation and exits; it does not daemonize itself. FDIC
call reports land roughly 30-45 days after quarter-end, so trigger it a few weeks
into February, May, August and November via the OS scheduler:

**cron** (Linux/macOS dev or prod VM):
```
0 6 5 2,5,8,11 * cd /path/to/banklens && pwsh scripts/run_orchestrator.ps1 >> data/orchestration_runs/cron.log 2>&1
```

**Windows Task Scheduler**:
```
schtasks /Create /TN "BankLens Quarterly Refresh" /TR "powershell -File C:\path\to\banklens\scripts\run_orchestrator.ps1" /SC MONTHLY /MO 3 /D 5 /ST 06:00
```
