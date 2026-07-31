# platform/docker

Two separate compose files for two separate concerns — don't confuse them.

## `docker-compose.app.yml` — the app tier that's actually running today

Containerizes the REST bridge (`services/api-gateway/Dockerfile`) and the quant
terminal (`frontend/apps/web/Dockerfile`), the two services that genuinely serve
requests in this project right now.

```powershell
powershell -File ../../scripts/docker_up.ps1     # or: docker compose -f docker-compose.app.yml up --build
# open http://localhost:8080
```

Mounts your local `data/` read-only — land data first with the usual scripts
(`run_vertical_slice.ps1`, `crosswalk.ps1`, etc.), this compose file doesn't land
anything itself. See `platform/k8s/README.md` for the Kubernetes equivalent.

## `docker-compose.dev.yml` — data infrastructure

Spins up Postgres/ClickHouse/MinIO/Redis — the stores the *master plan* calls for
at production scale.

**Postgres is real, not scaffolding**: it's the actual system of record for the
MCP server's per-tool-call audit log and the agent CLI's run history (see
`libs/python/banklens_common/src/banklens_common/db.py`) — both used to be flat
files only (`data/mcp_audit.jsonl`, `data/agent_runs/*.json`), which
`docs/runbooks/disaster-recovery.md` flagged as non-recoverable if lost. Start it
before running the MCP server, the REST bridge, or the agent CLI; if it's down,
both fall back to their old flat-file behavior with a one-time warning rather
than silently losing the audit trail.

**Prometheus + Grafana are also real, not scaffolding**: Prometheus scrapes the
REST bridge's actual `/metrics` endpoint (`services/api-gateway/src/bridge_server.py`,
`prometheus-client` backed); Grafana auto-provisions a real dashboard
("BankLens REST Bridge" — request rate, error rate, p50/p95/p99 latency by
route) against it, config in `platform/observability/`. Verified live: real
HTTP traffic generated against the bridge, confirmed via Prometheus's own API
that it scraped and stored the exact counts, then confirmed via Grafana's
datasource-proxy API that each dashboard panel's actual PromQL query returns
real numbers (see `CHANGELOG.md`) — not just "the containers started".
Grafana at `http://localhost:3000` (anonymous Viewer access enabled for local
dev; `GRAFANA_ADMIN_USER`/`PASSWORD` in `.env` for the admin/edit role).

**Keycloak + OPA are also real, not scaffolding**: gate every REST bridge
route except `/api/health`/`/metrics` behind a real signed OIDC token and a
real policy-engine authorization decision. See `platform/auth/README.md` for
the full setup, a real Keycloak 26 gotcha found and fixed along the way, and
how to verify it — including a real browser login flow, end to end.

ClickHouse/MinIO/Redis remain scaffolding from Phase 0 — no BankLens code reads/
writes them yet. Bring them up once a phase starts actually using them.

```powershell
copy ..\..\.env.example ..\..\.env    # then edit passwords
docker compose -f docker-compose.dev.yml up -d postgres prometheus grafana keycloak opa  # the real stuff
docker compose -f docker-compose.dev.yml up -d             # everything, including unused scaffolding
docker compose -f docker-compose.dev.yml ps
```

Host port for Postgres defaults to **55432**, not 5432 — see `POSTGRES_PORT` in
`.env.example`. A different project's native `postgresql-x64-18` Windows service
already owns 5432 on the reference dev machine; publishing there silently lost
that bind race (every client got "role banklens does not exist" — it was talking
to the wrong server). Container-internal port is still plain 5432, so
K8s/`docker-compose.app.yml` service-to-service traffic is unaffected.

| Service | Host port | Role |
|---|---|---|
| Postgres (+pgvector) | 55432 (→5432 in-container) | **Real**: audit log, agent run history. Scaffolded, unused: general OLTP/RAG |
| Prometheus | 9090 | **Real**: scrapes the bridge's `/metrics` every 5s |
| Grafana | 3000 | **Real**: "BankLens REST Bridge" dashboard, auto-provisioned |
| Keycloak | 8081 (→8080 in-container) | **Real**: OIDC login, gates the bridge |
| OPA | 8181 | **Real**: viewer/analyst authorization policy |
| ClickHouse | 8123 / 9000 | time-series serving (candles, metrics) — unused |
| MinIO | 9002 (API) / 9001 (console) | S3-compatible object store (lakehouse) — unused |
| Redis | 6379 | cache / rate-limit / queues — unused |
