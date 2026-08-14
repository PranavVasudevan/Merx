# Privacy and data retention

G4 (`docs/audit/04-remediation-prompts.md`). This covers the **user-generated
layer** only — your watchlists, your questions to the assistant, and the
system's record of tool calls. It does not cover bank data: every institution,
balance-sheet figure, filing excerpt, and market price in BankLens is public
information sourced from FDIC, SEC EDGAR, EBA/SRB and Tiingo (see
`config/sources.yaml`), not personal data about the bank or its customers.

## What is stored, and for how long

All of it lives in the Postgres instance described in
`libs/python/banklens_common/src/banklens_common/db.py`. Nothing here is a
flat file a purge job could miss — the schema in that module is the single
source of truth for every table below.

| Table | What it holds | Retention |
|---|---|---|
| `watchlists` | The banks (`cert`) you've starred, when, and any free-text note you attached (`note`) | Kept until you remove it — active state, not a log |
| `watchlist_rules` | Alert thresholds you've set on a watched bank (metric, operator, threshold) | Kept until you remove it |
| `saved_screens` | Named screener filter sets you've saved | Kept until you remove it |
| `alerts` | Notifications generated when one of your rules trips | Kept until you remove it |
| `agent_runs` | Every question you asked the AI assistant, its answer, which persona/model answered, and a pointer to the full transcript JSON under `data/agent_runs/` | **90 days** by default (`BANKLENS_AGENT_RUN_RETENTION_DAYS`), then both the row and the transcript file are deleted |
| `mcp_audit_log` | A record of every tool call the system executed on the assistant's behalf (tool name, arguments, success/failure, latency) | **90 days** by default (`BANKLENS_AUDIT_LOG_RETENTION_DAYS`), then the row is deleted |

Watchlists and their rules/screens/alerts are treated as active product state,
not logs — there is no time limit on them because you're expected to keep
using them, but you can delete all of it at any time (see below). Agent-run
transcripts and the audit log are logs: free text you typed and a record of
what the system did in response is a liability the longer it sits around
unused, so both default to a 90-day window, configurable via the environment
variables above.

## How retention is enforced

`pipelines/orchestration/src/banklens_orchestration/purge_cli.py` deletes
every `agent_runs` row (and its transcript file on disk) and every
`mcp_audit_log` row older than the configured retention window. It is wired
as the `purge_expired_user_data` stage in the existing quarterly-refresh DAG
(`pipelines/orchestration/src/banklens_orchestration/quarterly_refresh.py`),
so it runs on every scheduled refresh without a second scheduler — this
product runs on a $0 budget with no separate cron infrastructure.

**Honest caveat on cadence:** the quarterly refresh runs roughly every three
months (a few weeks after FDIC call-report data lands — see that module's
docstring), which is coarser than the 90-day default retention window. A row
purgeable on day 90 may not actually be deleted until day ~180 if the next
scheduled run hasn't happened yet. If a tighter bound is needed, run
`purge_cli.py` directly on its own, more frequent cron/Task Scheduler entry —
it takes no arguments that depend on the rest of the refresh, so this
requires no code change, only a second schedule entry.

The purge job fails open, consistent with every other Postgres-backed feature
in this codebase (see `db.DbUnavailable` and A8's `DATABASE_URL` work): if
Postgres is unreachable when the DAG runs, the stage records `{"skipped":
"..."}` in the run log rather than failing the whole quarterly refresh.

## Exporting and deleting your own data

Two authenticated, self-service routes, gated the same way `/api/watchlist`
already is (viewer role, scoped server-side to your own `sub` claim from your
OIDC token — you can never see or delete another user's data through these
routes):

- `GET /api/privacy/export` — returns everything above that's attributable to
  you, as one JSON document: your watchlist, watchlist rules, saved screens,
  alerts, and agent-run transcripts.
- `DELETE /api/privacy/data` — deletes all of the above for you, and returns a
  per-table count of what was removed as a receipt.

Both are implemented in `services/api-gateway/src/bridge_server.py`
(`/api/privacy/export`, `/api/privacy/data`) on top of
`export_user_data`/`delete_user_data` in
`libs/python/banklens_common/src/banklens_common/db.py`.

## Known gap: the audit log is not reliably scoped to you today

`mcp_audit_log.requester` identifies the *MCP client* that made a tool
call — in practice, the persona name (e.g. `agent:screener`), not the human
who asked the question. The stdio MCP protocol
(`services/mcp-server/src/banklens_mcp/server.py`) carries no per-request
auth header the way an HTTP request does, so there is currently no plumbing
that threads your `sub` claim from the authenticated bridge request down into
an individual tool call's audit row. `export_user_data`/`delete_user_data`
still query `mcp_audit_log` by your `sub`, for a stable response shape and so
this starts working the moment that plumbing exists, but as shipped today it
will typically return zero audit-log rows for a real user — the audit trail
exists and is retention-purged like everything else here, it just isn't
yet attributable to an individual user. Fixing that requires changes in
`services/mcp-server` and `services/agents` (threading the caller's roles the
way G2 already threads roles into `run_agent`, extended to identity), which
is out of this item's scope but tracked here rather than silently assumed
away.

Similarly, **`agent_runs.user_sub` is only populated for runs started through
the authenticated bridge** (`POST /api/assistant/ask`). It stays `NULL` for
runs started through the standalone local CLI
(`services/agents/src/banklens_agents/cli.py`), which has no HTTP request or
token to read a subject claim from — there is no user to attribute a
CLI-triggered run to.

## Deployment note (EU users)

BankLens serves EU institutional data (EBA/SRB sources, see
`config/sources.yaml`) to EU users. The bank data itself is public and
non-personal, so it carries no GDPR obligation on its own. The obligations in
this document — the retention windows and the export/delete routes above —
are what apply to the personal, user-generated layer regardless of where a
user is located.
