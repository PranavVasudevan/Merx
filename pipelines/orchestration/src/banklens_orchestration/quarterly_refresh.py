"""The real scheduled BankLens refresh: FDIC population -> CIK crosswalk -> market
data / SEC filings -> peer clustering -> deposit-flight retrain, wired to the exact
`run()` functions the manual CLIs already call (no subprocess, no duplicated logic
— a failure here is a real Python exception with a real traceback, not a shelled-out
exit code to re-parse).

FDIC call reports land roughly 30-45 days after quarter-end, so this is meant to be
triggered quarterly, a few weeks into Feb/May/Aug/Nov — see the cron/Task Scheduler
examples in `pipelines/orchestration/README.md`. This module only defines and runs
the DAG for one invocation; it does not daemonize itself (see dag.py's docstring for
why: that is the Airflow/Prefect swap-in point, not something to half-build here).

    powershell -File scripts/run_orchestrator.ps1
    powershell -File scripts/run_orchestrator.ps1 -Repdte 20260630 -LandSod
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# parents[4], NOT [3]: this file sits at
# <repo>/pipelines/orchestration/src/banklens_orchestration/quarterly_refresh.py,
# so [3] is `pipelines/` and only [4] is the repo root. The sibling ingestion CLIs
# at identical depth already use [4]. Found live by running this in a container,
# where the wrong root made --data-dir default to `<repo>/pipelines/data` and the
# job died on PermissionError; locally it stayed invisible because the PowerShell
# wrapper sets PYTHONPATH itself, so the bogus sys.path entry below never mattered.
REPO = Path(__file__).resolve().parents[4]
for rel in ("pipelines/ingestion/src", "pipelines/transforms/src"):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_ingestion import (  # noqa: E402
    clustering_cli, crosswalk_cli, deposit_flight_cli, filings_cli, market_cli,
    population_land_cli, sod_cli,
)

from .dag import Stage, run_dag  # noqa: E402


def build_dag(*, repdte: str, quarters: int, data_dir: Path,
              land_sod: bool, sod_year: int, filings_limit: int,
              market_limit: int) -> list[Stage]:
    """The dependency graph for one refresh. A plain list of `Stage`s — this is the
    exact shape an Airflow DAG or Prefect flow would wrap, so upgrading later is a
    mechanical translation, not a redesign."""
    repdtes = population_land_cli.recent_quarters(repdte, quarters)
    stages = [
        Stage("land_population",
              lambda: population_land_cli.run(repdtes, data_dir),
              retries=3, retry_delay_s=15),
        Stage("crosswalk",
              lambda: crosswalk_cli.run(repdte, data_dir, verify=None),
              depends_on=("land_population",), retries=2, retry_delay_s=10),
        Stage("market_data",
              lambda: market_cli.run(data_dir, limit=market_limit, refresh_days=1,
                                     start_date="2023-01-01"),
              depends_on=("crosswalk",), retries=2, retry_delay_s=10),
        Stage("filings",
              lambda: filings_cli.run(limit=filings_limit, repdte=repdte, data_dir=data_dir),
              depends_on=("crosswalk",), retries=2, retry_delay_s=10),
        # Both derived-model stages only need Bronze/Silver population, not the
        # crosswalk/market/filings branch — they run independently so a filings
        # rate-limit hiccup can't block the clustering refresh.
        Stage("clustering",
              lambda: clustering_cli.run(repdte, data_dir, highlight_cert=6976, k_override=None),
              depends_on=("land_population",), retries=1),
        Stage("deposit_flight_retrain",
              lambda: deposit_flight_cli.run(data_dir),
              depends_on=("land_population",), retries=1),
    ]
    if land_sod:
        # FDIC Summary of Deposits is annual (published once, ~June), not quarterly —
        # opt-in per run so a routine quarterly refresh doesn't re-pull ~76k branch
        # rows for no reason.
        stages.append(Stage("summary_of_deposits",
                            lambda: sod_cli.run(sod_year, data_dir),
                            retries=2, retry_delay_s=15))
    return stages


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run the quarterly BankLens Bronze->Silver->Gold + derived-model refresh")
    p.add_argument("--repdte", default="20260331", help="latest report date (YYYYMMDD)")
    p.add_argument("--quarters", type=int, default=1,
                   help="how many quarters back from --repdte to (re)land")
    p.add_argument("--data-dir", type=Path, default=REPO / "data")
    p.add_argument("--land-sod", action="store_true",
                   help="also re-land FDIC Summary of Deposits (annual, slow — off by default)")
    p.add_argument("--sod-year", type=int, default=2025)
    p.add_argument("--filings-limit", type=int, default=100)
    p.add_argument("--market-limit", type=int, default=200)
    args = p.parse_args()

    stages = build_dag(
        repdte=args.repdte, quarters=args.quarters, data_dir=args.data_dir,
        land_sod=args.land_sod, sod_year=args.sod_year,
        filings_limit=args.filings_limit, market_limit=args.market_limit)

    run_log = args.data_dir / "orchestration_runs" / "quarterly_refresh.jsonl"
    print(f"Running quarterly refresh DAG for {args.repdte} "
          f"({len(stages)} stages) -> {run_log}")
    results = run_dag(stages, run_log=run_log)

    for r in results:
        status = "OK    " if r.ok else "FAILED"
        detail = f" — {r.error}" if r.error else ""
        print(f"[{status}] {r.name} ({r.attempts} attempt(s), {r.duration_s:.1f}s){detail}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} of {len(results)} stage(s) failed.")
        raise SystemExit(1)
    print(f"\nAll {len(results)} stages succeeded.")


if __name__ == "__main__":
    main()
