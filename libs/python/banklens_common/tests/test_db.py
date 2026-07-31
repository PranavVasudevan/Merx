"""banklens_common.db tests — the real Postgres wiring for the MCP audit log and
agent-run history (see docs/runbooks/disaster-recovery.md, which flagged both as
"not recoverable if deleted... add real log shipping before this matters").

Env/DSN tests are hermetic. The round-trip test needs a real reachable Postgres
(`docker compose -f platform/docker/docker-compose.dev.yml up -d postgres`) and
SKIPs, not fails, if one isn't running — same convention as
services/mcp-server/tests/test_mcp.py's require_landed_data().
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_common import db  # noqa: E402


class SkipTest(Exception):
    pass


def _clear_env(monkeypatch_keys):
    saved = {k: os.environ.pop(k, None) for k in monkeypatch_keys}
    return saved


def _restore_env(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_get_falls_back_to_default_when_key_absent_everywhere():
    """Uses a key that's genuinely in neither os.environ nor .env on any dev
    machine, so this doesn't depend on whether a local .env happens to exist
    (unlike POSTGRES_HOST/PORT/etc, which real dev machines DO set in .env)."""
    saved = _clear_env(["POSTGRES_SSLMODE"])
    try:
        assert db._get("POSTGRES_SSLMODE", "disable") == "disable"
    finally:
        _restore_env(saved)


def test_dsn_env_var_overrides_default():
    saved = _clear_env(["POSTGRES_PORT"])
    os.environ["POSTGRES_PORT"] = "55432"
    try:
        assert "port=55432" in db._dsn()
    finally:
        os.environ.pop("POSTGRES_PORT", None)
        _restore_env(saved)


def test_unreachable_host_raises_db_unavailable_not_a_raw_driver_error():
    """The whole point of DbUnavailable: callers (server.py's _audit, cli.py's
    agent-run indexing) catch ONE exception type to trigger their JSONL/disk
    fallback, regardless of which underlying libpq error caused it."""
    saved = _clear_env(["POSTGRES_HOST", "POSTGRES_PORT"])
    os.environ["POSTGRES_HOST"] = "127.0.0.1"
    os.environ["POSTGRES_PORT"] = "1"          # nothing listens on port 1
    try:
        try:
            db.connect()
            raise AssertionError("expected DbUnavailable, connection unexpectedly succeeded")
        except db.DbUnavailable:
            pass
    finally:
        _restore_env(saved)


def _require_live_db():
    try:
        db.connect().close()
    except db.DbUnavailable as e:
        raise SkipTest(f"no reachable Postgres ({e}) — "
                       f"docker compose -f platform/docker/docker-compose.dev.yml up -d postgres") from e


def test_record_and_fetch_audit_round_trip():
    _require_live_db()
    db.record_audit("test_db_py_roundtrip", {"cert": 999999}, True, 1.23)
    rows = db.fetch_recent_audit(50)
    match = next((r for r in rows if r["tool"] == "test_db_py_roundtrip"), None)
    assert match is not None
    assert match["arguments"] == {"cert": 999999}
    assert match["ok"] is True
    conn = db.get_conn()
    conn.execute("DELETE FROM mcp_audit_log WHERE tool = %s", ("test_db_py_roundtrip",))


def test_record_and_fetch_agent_run_round_trip():
    _require_live_db()
    db.record_agent_run("macro_stress", "ollama", "llama3.2:1b", "test_db_py question",
                        "test_db_py answer", True, "data/agent_runs/test_db_py.json")
    rows = db.fetch_recent_agent_runs(50)
    match = next((r for r in rows if r["question"] == "test_db_py question"), None)
    assert match is not None
    assert match["answer"] == "test_db_py answer"
    assert match["transcript_path"] == "data/agent_runs/test_db_py.json"
    conn = db.get_conn()
    conn.execute("DELETE FROM agent_runs WHERE question = %s", ("test_db_py question",))


if __name__ == "__main__":
    failures = skipped = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except SkipTest as e:
                skipped += 1; print(f"SKIP  {name}: {e}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001 — a crash must not abort the rest
                failures += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    tail = f" ({skipped} skipped)" if skipped else ""
    print("\n" + (f"OK - all tests passed{tail}" if not failures
                  else f"{failures} test(s) failed{tail}"))
    sys.exit(1 if failures else 0)
