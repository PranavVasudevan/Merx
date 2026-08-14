# Disaster recovery — user-generated data layer

Scope: this runbook covers the **user-generated layer** — the MCP audit log
and agent-run transcripts (`libs/python/banklens_common/src/banklens_common/db.py`)
— not the bank data itself. Bank data (Bronze/Silver/Gold) is public,
reproducible from the landing scripts against each source's live API, and
carries its own provenance/checksum per partition; losing a local `data/`
checkout is an inconvenience (re-run the landing CLIs), not data loss.

## What's actually at risk

| Artifact | System of record | Local fallback |
|---|---|---|
| MCP tool-call audit log | Postgres `mcp_audit_log` table | `data/mcp_audit.jsonl` |
| Agent-run transcripts (questions, tool calls, answers) | Postgres `agent_runs` table | `data/agent_runs/*.json` |
| Watchlists, saved screens, watchlist rules, alerts | Postgres only | none — see below |

Postgres (`platform/docker/docker-compose.dev.yml`'s `postgres` service,
`pgvector/pgvector:pg16`) is the real system of record for all of the above.
Before this table existed, the audit log and agent-run history were flat
files only, with no backup story — this runbook originally flagged that as
"not recoverable if deleted", which is the reason `db.py` exists at all. That
gap is now closed for the audit log and agent-run history specifically
(both have a local-file fallback, below); it is **not** closed for the
watchlist/screens/rules/alerts tables, which have no fallback and live in
Postgres only.

## Fail-open behavior (by design, and where it stops)

`db.get_conn()`/`db.connect()` raise `DbUnavailable` on any
`psycopg.OperationalError` (Postgres unreachable, wrong credentials, etc.),
with a 3-second connect timeout so a dead DB doesn't hang a request.

- **MCP server** (`services/mcp-server/src/banklens_mcp/server.py`'s
  `_audit()`): catches any exception from `record_audit()` (including
  `DbUnavailable`) and falls back to appending JSON lines to
  `data/mcp_audit.jsonl`, printing one warning to stderr per process (not
  once per call) so the log doesn't spam. **This is a deliberate
  availability tradeoff**: losing the audit trail's queryability is
  low-stakes compared to blocking every tool call because Postgres is
  briefly down.
- **Agent-run recording** (`services/api-gateway/src/bridge_server.py`'s
  `RUNS_DIR`, `data/agent_runs/*.json`): written per-run regardless of
  Postgres state — the JSON file is the primary write path for the
  transcript itself; `record_agent_run()` additionally mirrors it into
  Postgres when reachable.
- **Everything else that touches Postgres directly** (watchlist,
  saved screens, rules, alerts, filing-chunk search) has **no** local
  fallback and simply fails the request with `DbUnavailable` (mapped to a
  503 by the bridge) when Postgres is unreachable — unlike the audit
  log/agent-run path, this is a real, user-visible outage, not a silent
  degradation.

This is the opposite tradeoff `services/api-gateway/src/auth.py` makes for
authentication/authorization (`AuthUnavailable` also maps to 503) — the two
failure modes are handled the same way at the HTTP layer (fail closed with a
clear error), but for very different reasons: auth fails closed because an
open auth gate is a real vulnerability, while the watchlist/screens/rules
tables fail closed simply because there's nowhere else to write them.

## Recovery procedures

**Postgres data loss (container/volume deleted, corrupted DB):**

1. Bank data is unaffected — it never lived in Postgres.
2. The audit log and agent-run history are **partially** recoverable from
   the local JSONL/JSON fallback files IF the fallback path was ever
   exercised (i.e. Postgres was down for some window and the MCP server or
   bridge fell back to disk during that window). There is no tool today
   that replays `data/mcp_audit.jsonl` back into a fresh `mcp_audit_log`
   table — this would be a straightforward one-off script (parse each JSON
   line, call `db.record_audit()` for each) if that history needs to be
   restored, but it does not exist yet.
3. Watchlists, saved screens, watchlist rules and alerts have **no recovery
   path** if the Postgres volume is lost — they were never written anywhere
   else. Back up the `postgres` volume (`pg_dump` on a schedule, or a
   managed host's own backup feature — see `libs/python/banklens_common/src/
   banklens_common/db.py`'s `DATABASE_URL` support for pointing at a free
   hosted tier like Neon/Supabase, both of which provide point-in-time
   recovery on their free tiers) if this data matters to you.

**Postgres briefly unreachable (network blip, container restart):**

No action needed. The audit log and agent-run paths degrade to local files
automatically; other routes return a clear 503 until Postgres comes back,
and no data is lost once it does (the local-fallback writes for the audit
log/agent-run path are never replayed automatically into Postgres, though —
see the manual-replay note above if reconciling the two matters to you).

**Retention / expected data loss (by design, not a disaster):** `db.py`'s
`agent_run_retention_days()` / `audit_log_retention_days()` (default 90 days
each, `BANKLENS_AGENT_RUN_RETENTION_DAYS` / `BANKLENS_AUDIT_LOG_RETENTION_DAYS`)
back a scheduled purge job (`pipelines/orchestration/src/banklens_orchestration/
purge_cli.py`, run as part of the quarterly refresh DAG's
`purge_expired_user_data` stage — see `pipelines/orchestration/README.md`).
Rows older than the retention window are deleted on purpose (G4 — data
minimization for the user-generated layer); this is expected loss, not
something to restore from backup.
