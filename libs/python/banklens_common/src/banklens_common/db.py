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

CREATE TABLE IF NOT EXISTS watchlists (
    user_sub TEXT NOT NULL,
    cert INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_sub, cert)
);
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
