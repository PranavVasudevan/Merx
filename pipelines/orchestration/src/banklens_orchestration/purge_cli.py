"""G4 (docs/audit/04-remediation-prompts.md): scheduled retention purge for the
user-generated layer — agent-run transcripts (DB row + the JSON file on disk)
and the MCP audit log. Wired as its own DAG stage in
quarterly_refresh.build_dag(), so it runs on the same cadence as the rest of
the refresh rather than needing a second scheduler the product's $0 budget
can't add. That cadence (roughly quarterly, per quarterly_refresh's own
docstring) is coarser than the 90-day default retention window — a row can
sit for up to ~180 days before this runs again, not exactly 90 — see
docs/privacy.md for that tradeoff spelled out. Ops that need a tighter bound
can still cron this module directly at any interval; it takes no arguments
that depend on the rest of the refresh.

Watchlists/watchlist_rules/saved_screens/alerts are NOT purged here — they are
active user state, not logs, and are kept until the user deletes them via
DELETE /api/watchlist (etc.) or the blanket DELETE /api/privacy/data.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
for rel in ("libs/python/banklens_common/src",):
    p = REPO / rel
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from banklens_common import db  # noqa: E402


def run() -> dict:
    try:
        purged_paths = db.purge_expired_agent_runs()
        purged_audit_rows = db.purge_expired_audit_log()
    except db.DbUnavailable as exc:
        # Same fail-open posture as alerts_cli/A8 — an unconfigured/unreachable
        # DB in a given environment must not fail the whole quarterly refresh
        # over a housekeeping stage.
        return {"skipped": str(exc)}

    files_deleted = 0
    for rel_path in purged_paths:
        path = REPO / rel_path
        if not path.exists():
            continue  # already gone (manual cleanup, prior partial run) — not a count-worthy delete
        try:
            path.unlink()
            files_deleted += 1
        except OSError:
            pass  # the DB row is already gone; a stray file isn't worth failing the stage over

    return {
        "agent_runs_purged": len(purged_paths),
        "transcript_files_deleted": files_deleted,
        "audit_log_rows_purged": purged_audit_rows,
    }


if __name__ == "__main__":
    print(run())
