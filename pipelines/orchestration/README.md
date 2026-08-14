# `banklens_orchestration`

The scheduled quarterly refresh: FDIC population -> CIK crosswalk -> market data /
SEC filings -> peer clustering -> deposit-flight retrain -> alert evaluation ->
retention purge, wired to the exact `run()` functions the manual `pipelines/ingestion`
CLIs already call (no subprocess shelling-out, no duplicated logic — a stage failure
is a real Python exception with a real traceback).

## Why a hand-rolled DAG runner, not Airflow/Prefect

`dag.py` is ~80 dependency-free lines: topological ordering, retries with backoff,
upstream-failure short-circuiting, and a durable JSONL run log. At this data volume
(six sequential/branching stages, one refresh per quarter) that's the whole job —
Airflow needs a metadata DB, webserver and scheduler process; Prefect's dependency
tree alone is 60+ packages. `quarterly_refresh.build_dag()` returns a plain list of
`Stage` objects (name, callable, `depends_on`, retry count), which is exactly the
shape either framework's task API would want if pipeline count or team size ever
outgrows this — a mechanical translation, not a redesign.

## The DAG

```
land_population
   ├── crosswalk
   │      ├── market_data
   │      └── filings
   ├── clustering
   └── deposit_flight_retrain
          └── evaluate_alerts (depends on clustering + deposit_flight_retrain)
purge_expired_user_data (independent — runs regardless of the data stages above)
[summary_of_deposits]   (opt-in via --land-sod; annual data, not part of every run)
```

`market_data` and `filings` branch off `crosswalk` independently so a Tiingo/SEC
rate-limit hiccup on one can't block the other. `clustering` and
`deposit_flight_retrain` only need the landed population, not the crosswalk/market/
filings branch, so they run even if SEC/market data lands late. `evaluate_alerts`
(D2 — watchlist threshold rules) runs after both derived-model stages specifically so
cluster- and risk-leaderboard-based rules see this run's freshly retrained state, not
a stale one from before the refresh. `purge_expired_user_data` (G4 — retention purge
for agent-run transcripts and the MCP audit log) has no data-stage dependency at all:
it operates on `banklens_common.db`, not the Bronze/Silver/Gold layer, so a bad
market-data pull shouldn't also block housekeeping.

## Safety checks around the run

- **Durable-volume assertion** (`_assert_durable_volume`, gated by
  `BANKLENS_REQUIRE_DURABLE_VOLUME=true`): refuses to run if `--data-dir` resolves to
  a Kubernetes `emptyDir` (detected via `/proc/mounts`, since an emptyDir's mount
  source always contains `kubernetes.io~empty-dir` regardless of provisioner) — a
  successful refresh into an emptyDir would silently vanish on the next pod restart
  while the bridge kept serving stale data. `platform/k8s/base/refresh-cronjob.yaml`
  sets this env var; the dev overlay patches the volume to a real PVC
  (`platform/k8s/overlays/dev/refresh-data-patch.yaml`) so the base manifest's
  default `emptyDir: {}` is caught rather than silently accepted.
- **Post-run partition check** (`_missing_partitions`): after `run_dag()` returns,
  verifies every expected `data/bronze/source=fdic/population/repdte=<q>/records.json`
  partition actually landed on disk — a stage reporting success only means its
  function returned without raising, not that the write persisted where the bridge
  will actually look for it.

Either check failing exits non-zero, so a scheduler (cron, Task Scheduler, the K8s
CronJob) sees a real failure rather than a silent no-op.

## Running it

Interactively:

```powershell
powershell -File scripts/run_orchestrator.ps1
powershell -File scripts/run_orchestrator.ps1 -Repdte 20260630 -LandSod -SodYear 2026
```

or directly:

```powershell
python -m banklens_orchestration.quarterly_refresh --repdte 20260331 --quarters 1
```

Every run writes a durable JSONL log to `data/orchestration_runs/quarterly_refresh.jsonl`
(one line per stage: name, attempt count, duration, ok/error) via `dag.run_dag()`.

## Scheduling

FDIC call reports land roughly 30-45 days after quarter-end, so this is meant to run
a few weeks into February, May, August and November — not on quarter-end itself,
which would land an empty or stale slice.

The real, currently-registered schedule is `platform/k8s/base/refresh-cronjob.yaml`'s
Kubernetes CronJob: `0 6 5 2,5,8,11 *` — 06:00 UTC on the 5th of Feb/May/Aug/Nov. This
module only defines and runs the DAG for **one invocation**; it does not daemonize
itself (see `dag.py`'s docstring — daemonizing is the Airflow/Prefect swap-in point,
not something to half-build here), so something external has to invoke it on a
schedule. Outside Kubernetes, the equivalent is a `cron` entry or a Windows Task
Scheduler task running `scripts/run_orchestrator.ps1` on the same days.

Example `cron` entry (Linux, adjust paths):

```cron
0 6 5 2,5,8,11 * cd /opt/banklens && pwsh -File scripts/run_orchestrator.ps1 >> /var/log/banklens-refresh.log 2>&1
```

Windows Task Scheduler: trigger "Monthly", months February/May/August/November, day
5, action `powershell.exe -File C:\banklens\scripts\run_orchestrator.ps1`.
