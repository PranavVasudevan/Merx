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

REPO = Path(__file__).resolve().parents[5]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    tool TEXT NOT NULL,
    arguments JSONB NOT NULL,
    ok BOOLEAN NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS mcp_audit_log_ts_idx ON mcp_audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS mcp_audit_log_tool_idx ON mcp_audit_log (tool);

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

CREATE TABLE IF NOT EXISTS watchlists (
    user_sub TEXT NOT NULL,
    cert INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_sub, cert)
);
"""

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


def _dsn() -> str:
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
                  ts: datetime.datetime | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO mcp_audit_log (ts, tool, arguments, ok, latency_ms) "
        "VALUES (%s, %s, %s, %s, %s)",
        (ts or datetime.datetime.now(datetime.timezone.utc), tool,
         json.dumps(arguments, default=str), ok, latency_ms),
    )


def fetch_recent_audit(limit: int = 50) -> list[dict]:
    conn = get_conn()
    cols = ("id", "ts", "tool", "arguments", "ok", "latency_ms")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM mcp_audit_log ORDER BY ts DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def record_agent_run(persona: str, provider: str, model: str | None, question: str,
                      answer: str, ok: bool, transcript_path: str,
                      ts: datetime.datetime | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO agent_runs (ts, persona, provider, model, question, answer, ok, "
        "transcript_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (ts or datetime.datetime.now(datetime.timezone.utc), persona, provider, model,
         question, answer, ok, transcript_path),
    )


def fetch_recent_agent_runs(limit: int = 50) -> list[dict]:
    conn = get_conn()
    cols = ("id", "ts", "persona", "provider", "model", "question", "answer", "ok",
            "transcript_path")
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM agent_runs ORDER BY ts DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


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
        "SELECT cert, created_at FROM watchlists WHERE user_sub = %s ORDER BY created_at DESC",
        (user_sub,),
    ).fetchall()
    return [{"cert": cert, "created_at": created_at} for cert, created_at in rows]
