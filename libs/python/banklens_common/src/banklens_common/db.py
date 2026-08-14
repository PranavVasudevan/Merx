"""Real Postgres wiring for BankLens — audit log + agent run history.

Talks to the `postgres` service in `platform/docker/docker-compose.dev.yml`
(pgvector/pgvector:pg16). This is the actual system of record for the two
artifacts that used to be flat files only (`data/mcp_audit.jsonl`,
`data/agent_runs/*.json`) — see `docs/runbooks/disaster-recovery.md`, which
flagged both as "not recoverable if deleted... add real log shipping before
this matters." This module is that log shipping.

Connection settings come from the same env vars as the compose file
(POSTGRES_USER/PASSWORD/DB, see .env.example) plus POSTGRES_HOST/POSTGRES_PORT
for wherever the container is actually reachable (localhost:5432 for
`docker compose up`, overridden in Docker/K8s deployments where the DB has a
service name instead of localhost).

DATABASE_URL, if set, takes precedence over all of the above — free hosted
Postgres tiers (Neon, Supabase) issue a single connection string with
`sslmode=require` baked in rather than discrete host/port/user/password
values, and psycopg's `connect()` accepts a `postgresql://...` URI natively
(libpq conninfo supports both keyword and URI forms), so no parsing is
needed here — the string is passed straight through.

Usage:
    docker compose -f platform/docker/docker-compose.dev.yml up -d postgres
    (schema is created automatically on first connection — see init_schema)
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path

import psycopg

from . import embeddings

REPO = Path(__file__).resolve().parents[5]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    tool TEXT NOT NULL,
    arguments JSONB NOT NULL,
    ok BOOLEAN NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    requester TEXT NOT NULL DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS mcp_audit_log_ts_idx ON mcp_audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS mcp_audit_log_tool_idx ON mcp_audit_log (tool);
-- Column added after the table already existed in some dev/CI databases —
-- CREATE TABLE IF NOT EXISTS above is a no-op there, so add it explicitly too.
-- Must run BEFORE the index below, which references the column.
ALTER TABLE mcp_audit_log ADD COLUMN IF NOT EXISTS requester TEXT NOT NULL DEFAULT 'unknown';
CREATE INDEX IF NOT EXISTS mcp_audit_log_requester_idx ON mcp_audit_log (requester);

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    persona TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    transcript_path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_runs_ts_idx ON agent_runs (ts DESC);
-- G4 — the caller's subject claim, so a transcript can be scoped to the user
-- who asked the question for export/delete (docs/privacy.md). Nullable: runs
-- started outside the authenticated bridge (services/agents/src/banklens_agents/
-- cli.py's local CLI) have no HTTP claims to attach one from.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS user_sub TEXT;
CREATE INDEX IF NOT EXISTS agent_runs_user_idx ON agent_runs (user_sub);

CREATE TABLE IF NOT EXISTS watchlists (
    user_sub TEXT NOT NULL,
    cert INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_sub, cert)
);
-- D2 (docs/audit/04-remediation-prompts.md): free-text analyst notes per
-- watched bank. Same after-the-fact ADD COLUMN pattern as mcp_audit_log's
-- requester column above, for the same reason (existing dev/CI databases).
ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS note TEXT;

-- D2 — per-metric threshold rules on a watched bank ("uninsured deposits move
-- more than 3pp", "X-Ray severity increases", "enters the top-25 risk
-- leaderboard"). One row per rule; `metric`/`operator`/`threshold` are used by
-- rule_type='metric_delta' or 'metric_threshold', `top_n` by
-- rule_type='risk_leaderboard_entry'. See banklens_orchestration.alerts_cli
-- for the evaluator that reads this table after every refresh.
CREATE TABLE IF NOT EXISTS watchlist_rules (
    id BIGSERIAL PRIMARY KEY,
    user_sub TEXT NOT NULL,
    cert INTEGER NOT NULL,
    rule_type TEXT NOT NULL,
    metric TEXT,
    operator TEXT,
    threshold DOUBLE PRECISION,
    top_n INTEGER,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS watchlist_rules_user_idx ON watchlist_rules (user_sub);
CREATE INDEX IF NOT EXISTS watchlist_rules_cert_idx ON watchlist_rules (cert);

-- D2 — named, persisted screener filter sets (same storage shape the D5 peer-
-- set builder will reuse for its own named lists).
CREATE TABLE IF NOT EXISTS saved_screens (
    id BIGSERIAL PRIMARY KEY,
    user_sub TEXT NOT NULL,
    name TEXT NOT NULL,
    filters JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS saved_screens_user_idx ON saved_screens (user_sub);

-- D2 — alerts an evaluation pass wrote after a rule tripped. `seen` lets the
-- UI distinguish "new since your last visit" without deleting the record.
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    user_sub TEXT NOT NULL,
    cert INTEGER NOT NULL,
    rule_id BIGINT,
    message TEXT NOT NULL,
    quarter TEXT,
    triggered_at TIMESTAMPTZ NOT NULL,
    seen BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS alerts_user_idx ON alerts (user_sub, triggered_at DESC);
"""

# Feature 17 (Tier 6 capstone) — real SEC 10-K Item 1A chunks + embeddings.
# Separate from _SCHEMA: this is the one statement in the whole schema that can
# fail on a Postgres role without CREATE-extension privilege, and every OTHER
# caller of get_conn() (audit log, agent runs, watchlist) has nothing to do with
# pgvector — they shouldn't fail to connect just because this one feature can't
# install its extension. Applied lazily, on first filings-specific call only.
_FILINGS_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS filing_chunks (
    id BIGSERIAL PRIMARY KEY,
    cik BIGINT NOT NULL,
    cert INTEGER,
    ticker TEXT,
    name TEXT NOT NULL,
    accession TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    report_date TEXT NOT NULL,
    extraction_confidence TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS filing_chunks_cik_idx ON filing_chunks (cik);
CREATE INDEX IF NOT EXISTS filing_chunks_cert_idx ON filing_chunks (cert);
"""
_filings_schema_applied = False

_lock = threading.Lock()
_conn: psycopg.Connection | None = None


class DbUnavailable(RuntimeError):
    """Raised when Postgres can't be reached — callers decide their own fallback."""


def _dotenv(key: str) -> str | None:
    """Same minimal .env reader every other client in this repo hand-rolls
    (see anthropic_client.py) — no shared dotenv dependency, just consistency."""
    env_path = REPO / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def _get(key: str, default: str) -> str:
    return os.environ.get(key) or _dotenv(key) or default


# G4 — how long the user-generated logs (agent-run transcripts, MCP audit log)
# are kept before a scheduled purge deletes them (see
# pipelines/orchestration/src/banklens_orchestration/purge_cli.py and
# docs/privacy.md). 90 days is long enough to debug a recent incident or
# support request without turning the tables into an unbounded personal-data
# store. Watchlists/watchlist_rules/saved_screens/alerts are active user state,
# not logs — they are kept indefinitely but are user-deletable (see
# delete_user_data below), so they have no retention constant here.
def _retention_days(env_key: str, default_days: int) -> int:
    return int(_get(env_key, str(default_days)))


def agent_run_retention_days() -> int:
    return _retention_days("BANKLENS_AGENT_RUN_RETENTION_DAYS", 90)


def audit_log_retention_days() -> int:
    return _retention_days("BANKLENS_AUDIT_LOG_RETENTION_DAYS", 90)


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or _dotenv("DATABASE_URL")
    if url:
        return url
    host = _get("POSTGRES_HOST", "localhost")
    port = _get("POSTGRES_PORT", "5432")
    user = _get("POSTGRES_USER", "banklens")
    password = _get("POSTGRES_PASSWORD", "change_me_locally")
    dbname = _get("POSTGRES_DB", "banklens")
    return f"host={host} port={port} user={user} password={password} dbname={dbname}"


def get_conn() -> psycopg.Connection:
    """A lazily-created, process-wide connection with the schema already applied.

    Threading.Lock guards first-connect races (the MCP server and the REST
    bridge are both multi-threaded request handlers); psycopg connections
    themselves are not safe to share across concurrent statements, so callers
    that need real concurrency should open their own via `connect()` instead.
    """
    global _conn
    with _lock:
        if _conn is None or _conn.closed:
            try:
                _conn = psycopg.connect(_dsn(), autocommit=True, connect_timeout=3)
                _conn.execute(_SCHEMA)
            except psycopg.OperationalError as exc:
                _conn = None
                raise DbUnavailable(f"Postgres unreachable: {exc}") from exc
        return _conn


def connect() -> psycopg.Connection:
    """A fresh, independent connection (schema assumed already applied)."""
    try:
        return psycopg.connect(_dsn(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        raise DbUnavailable(f"Postgres unreachable: {exc}") from exc


def record_audit(tool: str, arguments: dict, ok: bool, latency_ms: float,
                  ts: datetime.datetime | None = None,
                  requester: str = "unknown") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO mcp_audit_log (ts, tool, arguments, ok, latency_ms, requester) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (ts or datetime.datetime.now(datetime.timezone.utc), tool,
         json.dumps(arguments, default=str), ok, latency_ms, requester),
    )


def fetch_recent_audit(limit: int = 50) -> list[dict]:
    conn = get_conn()
    cols = ("id", "ts", "tool", "arguments", "ok", "latency_ms", "requester")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM mcp_audit_log ORDER BY ts DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def record_agent_run(persona: str, provider: str, model: str | None, question: str,
                      answer: str, ok: bool, transcript_path: str,
                      ts: datetime.datetime | None = None,
                      user_sub: str | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO agent_runs (ts, persona, provider, model, question, answer, ok, "
        "transcript_path, user_sub) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ts or datetime.datetime.now(datetime.timezone.utc), persona, provider, model,
         question, answer, ok, transcript_path, user_sub),
    )


def fetch_recent_agent_runs(limit: int = 50) -> list[dict]:
    conn = get_conn()
    cols = ("id", "ts", "persona", "provider", "model", "question", "answer", "ok",
            "transcript_path", "user_sub")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM agent_runs ORDER BY ts DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def fetch_agent_runs_for_user(user_sub: str, limit: int = 10_000) -> list[dict]:
    conn = get_conn()
    cols = ("id", "ts", "persona", "provider", "model", "question", "answer", "ok",
            "transcript_path")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM agent_runs WHERE user_sub = %s ORDER BY ts DESC LIMIT %s",
        (user_sub, limit),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def fetch_audit_log_for_user(requester: str, limit: int = 10_000) -> list[dict]:
    """The audit log's `requester` column identifies the MCP client/persona that
    made a tool call (see services/mcp-server/src/banklens_mcp/server.py's
    `_requester`, set from the session's clientInfo.name), not the end user who
    triggered it — the stdio MCP protocol carries no per-request auth header to
    thread a real subject claim through. So this lookup is scoped by that same
    string for consistency with export_user_data, but for the actual product
    today (personas like "agent:screener") it will not match a real user_sub;
    documented as a known gap in docs/privacy.md rather than silently faked."""
    conn = get_conn()
    cols = ("id", "ts", "tool", "arguments", "ok", "latency_ms", "requester")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM mcp_audit_log WHERE requester = %s "
        "ORDER BY ts DESC LIMIT %s",
        (requester, limit),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def purge_expired_agent_runs(retention_days: int | None = None) -> list[str]:
    """Delete agent_runs rows older than the retention window. Returns the
    `transcript_path` of every deleted row so the caller (purge_cli) can also
    remove the corresponding transcript JSON file on disk — the DB row is not
    the only copy of a free-text question/answer."""
    conn = get_conn()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=retention_days if retention_days is not None else agent_run_retention_days())
    rows = conn.execute(
        "DELETE FROM agent_runs WHERE ts < %s RETURNING transcript_path", (cutoff,)
    ).fetchall()
    return [r[0] for r in rows]


def purge_expired_audit_log(retention_days: int | None = None) -> int:
    """Delete mcp_audit_log rows older than the retention window. Returns the
    number of rows deleted."""
    conn = get_conn()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=retention_days if retention_days is not None else audit_log_retention_days())
    cur = conn.execute("DELETE FROM mcp_audit_log WHERE ts < %s", (cutoff,))
    return cur.rowcount


def export_user_data(user_sub: str) -> dict:
    """G4 — everything stored against this user_sub, as one JSON-serialisable
    dict, for the self-service GET /api/privacy/export route."""
    return {
        "watchlist": fetch_watchlist(user_sub),
        "watchlist_rules": fetch_watchlist_rules(user_sub),
        "saved_screens": fetch_saved_screens(user_sub),
        "alerts": fetch_alerts(user_sub, limit=10_000),
        "agent_runs": fetch_agent_runs_for_user(user_sub),
        # See fetch_audit_log_for_user's docstring: real product traffic keys
        # audit rows by MCP client/persona, not user_sub, so this is almost
        # always empty today. Included anyway so the shape is stable and it
        # starts working the moment a real per-user requester is threaded in.
        "audit_log": fetch_audit_log_for_user(user_sub),
    }


def delete_user_data(user_sub: str) -> dict:
    """G4 — delete every row keyed on this user_sub, for the self-service
    DELETE /api/privacy/data route. Returns a count per table so the caller
    gets a real receipt, not just a 200."""
    conn = get_conn()
    counts = {}
    for table in ("watchlists", "watchlist_rules", "saved_screens", "alerts", "agent_runs"):
        cur = conn.execute(f"DELETE FROM {table} WHERE user_sub = %s", (user_sub,))
        counts[table] = cur.rowcount
    # Same caveat as fetch_audit_log_for_user: matches real rows only once a
    # per-user requester value exists upstream.
    cur = conn.execute("DELETE FROM mcp_audit_log WHERE requester = %s", (user_sub,))
    counts["mcp_audit_log"] = cur.rowcount
    return counts


def add_watchlist_item(user_sub: str, cert: int,
                        ts: datetime.datetime | None = None) -> None:
    conn = get_conn()
    # ON CONFLICT DO NOTHING: re-adding an already-watched bank is a no-op,
    # not an error — the frontend toggle button doesn't need to special-case it.
    conn.execute(
        "INSERT INTO watchlists (user_sub, cert, created_at) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_sub, cert) DO NOTHING",
        (user_sub, cert, ts or datetime.datetime.now(datetime.timezone.utc)),
    )


def remove_watchlist_item(user_sub: str, cert: int) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM watchlists WHERE user_sub = %s AND cert = %s", (user_sub, cert))


def fetch_watchlist(user_sub: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT cert, created_at, note FROM watchlists WHERE user_sub = %s ORDER BY created_at DESC",
        (user_sub,),
    ).fetchall()
    return [{"cert": cert, "created_at": created_at, "note": note} for cert, created_at, note in rows]


def update_watchlist_note(user_sub: str, cert: int, note: str) -> None:
    """D2 — free-text notes on a watched bank. No-op (0 rows) if the bank isn't
    on this user's watchlist; callers add it first via add_watchlist_item."""
    conn = get_conn()
    conn.execute(
        "UPDATE watchlists SET note = %s WHERE user_sub = %s AND cert = %s",
        (note, user_sub, cert),
    )


def add_watchlist_rule(user_sub: str, cert: int, rule_type: str, *, metric: str | None = None,
                        operator: str | None = None, threshold: float | None = None,
                        top_n: int | None = None, ts: datetime.datetime | None = None) -> int:
    """D2 — a threshold rule on a watched bank, evaluated by
    banklens_orchestration.alerts_cli after every refresh. See that module's
    docstring for the supported rule_type values."""
    conn = get_conn()
    row = conn.execute(
        "INSERT INTO watchlist_rules (user_sub, cert, rule_type, metric, operator, threshold, "
        "top_n, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (user_sub, cert, rule_type, metric, operator, threshold, top_n,
         ts or datetime.datetime.now(datetime.timezone.utc)),
    ).fetchone()
    return row[0]


def remove_watchlist_rule(user_sub: str, rule_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM watchlist_rules WHERE id = %s AND user_sub = %s", (rule_id, user_sub))


def fetch_watchlist_rules(user_sub: str | None = None) -> list[dict]:
    """`user_sub=None` (the orchestration evaluator's case) returns every
    user's rules — there is no per-request caller to scope it to there."""
    conn = get_conn()
    cols = ("id", "user_sub", "cert", "rule_type", "metric", "operator", "threshold",
            "top_n", "created_at")
    if user_sub is None:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM watchlist_rules").fetchall()
    else:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM watchlist_rules WHERE user_sub = %s", (user_sub,),
        ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def save_screen(user_sub: str, name: str, filters: dict,
                 ts: datetime.datetime | None = None) -> int:
    conn = get_conn()
    row = conn.execute(
        "INSERT INTO saved_screens (user_sub, name, filters, created_at) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (user_sub, name, json.dumps(filters), ts or datetime.datetime.now(datetime.timezone.utc)),
    ).fetchone()
    return row[0]


def fetch_saved_screens(user_sub: str) -> list[dict]:
    conn = get_conn()
    cols = ("id", "name", "filters", "created_at")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM saved_screens WHERE user_sub = %s ORDER BY created_at DESC",
        (user_sub,),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def delete_saved_screen(user_sub: str, screen_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM saved_screens WHERE id = %s AND user_sub = %s", (screen_id, user_sub))


def alert_already_recorded(rule_id: int, quarter: str) -> bool:
    """D2 — an evaluation pass can rerun for a quarter that's already been
    evaluated (a retried DAG stage, a manual re-run); this is the dedup check
    that keeps a persistently-tripped rule (e.g. "always in the top 25") from
    writing a duplicate alert every rerun of the SAME quarter. It does NOT
    suppress the rule tripping again in a genuinely LATER quarter."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE rule_id = %s AND quarter = %s LIMIT 1",
        (rule_id, quarter),
    ).fetchone()
    return row is not None


def record_alert(user_sub: str, cert: int, message: str, *, rule_id: int | None = None,
                  quarter: str | None = None, ts: datetime.datetime | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO alerts (user_sub, cert, rule_id, message, quarter, triggered_at, seen) "
        "VALUES (%s, %s, %s, %s, %s, %s, FALSE)",
        (user_sub, cert, rule_id, message, quarter,
         ts or datetime.datetime.now(datetime.timezone.utc)),
    )


def fetch_alerts(user_sub: str, limit: int = 50, unseen_only: bool = False) -> list[dict]:
    conn = get_conn()
    cols = ("id", "cert", "rule_id", "message", "quarter", "triggered_at", "seen")
    where = "WHERE user_sub = %s" + (" AND seen = FALSE" if unseen_only else "")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM alerts {where} ORDER BY triggered_at DESC LIMIT %s",
        (user_sub, limit),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def mark_alert_seen(user_sub: str, alert_id: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE alerts SET seen = TRUE WHERE id = %s AND user_sub = %s", (alert_id, user_sub))


def _ensure_filings_schema(conn: psycopg.Connection) -> None:
    global _filings_schema_applied
    if not _filings_schema_applied:
        conn.execute(_FILINGS_SCHEMA)
        _filings_schema_applied = True


def delete_filing_chunks_for_cik(cik: int) -> None:
    """Bronze is append-only, but this derived Postgres table isn't a source of
    record — re-landing a filer's chunks (a re-run, a fixed extraction) replaces
    its old rows rather than duplicating them alongside stale ones."""
    conn = get_conn()
    _ensure_filings_schema(conn)
    conn.execute("DELETE FROM filing_chunks WHERE cik = %s", (cik,))


def save_filing_chunks(rows: list[dict], ts: datetime.datetime | None = None) -> None:
    """Each row: {cik, cert, ticker, name, accession, filing_date, report_date,
    extraction_confidence, chunk_index, chunk_text, embedding (list[float])}."""
    if not rows:
        return
    conn = get_conn()
    _ensure_filings_schema(conn)
    now = ts or datetime.datetime.now(datetime.timezone.utc)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO filing_chunks (cik, cert, ticker, name, accession, filing_date, "
            "report_date, extraction_confidence, chunk_index, chunk_text, embedding, "
            "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
            [(r["cik"], r.get("cert"), r.get("ticker"), r["name"], r["accession"],
              r["filing_date"], r["report_date"], r["extraction_confidence"],
              r["chunk_index"], r["chunk_text"], embeddings.to_vector_literal(r["embedding"]),
              now) for r in rows],
        )


def search_filing_chunks(embedding: list[float], top_n: int = 8) -> list[dict]:
    """Cosine-nearest chunks to a query embedding. No approximate index (HNSW/
    IVFFlat) — at this corpus's real scale (thousands of chunks, not millions),
    pgvector's brute-force exact search is already fast and needs no tuning; an
    approximate index would trade correctness for speed this app doesn't need yet.
    """
    conn = get_conn()
    _ensure_filings_schema(conn)
    lit = embeddings.to_vector_literal(embedding)
    cols = ("cik", "cert", "ticker", "name", "accession", "filing_date", "report_date",
            "extraction_confidence", "chunk_index", "chunk_text")
    rows = conn.execute(
        f"SELECT {', '.join(cols)}, 1 - (embedding <=> %s::vector) AS similarity "
        f"FROM filing_chunks ORDER BY embedding <=> %s::vector LIMIT %s",
        (lit, lit, top_n),
    ).fetchall()
    return [dict(zip((*cols, "similarity"), row, strict=True)) for row in rows]


def filing_coverage_stats() -> dict:
    """How many filers/chunks are actually landed, and the confidence breakdown —
    the honest "what's covered" the /filings page and search results should be
    able to cite rather than imply full coverage."""
    conn = get_conn()
    _ensure_filings_schema(conn)
    total_filers, total_chunks = conn.execute(
        "SELECT COUNT(DISTINCT cik), COUNT(*) FROM filing_chunks").fetchone()
    by_confidence = dict(conn.execute(
        "SELECT extraction_confidence, COUNT(DISTINCT cik) FROM filing_chunks "
        "GROUP BY extraction_confidence").fetchall())
    return {"filers": total_filers or 0, "chunks": total_chunks or 0,
            "by_confidence": by_confidence}
