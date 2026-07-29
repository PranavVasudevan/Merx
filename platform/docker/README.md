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

## `docker-compose.dev.yml` — scaffolded data infrastructure, not yet wired to real code

Spins up Postgres/ClickHouse/MinIO/Redis — the stores the *master plan* calls for
at production scale. Honest status: this is infrastructure scaffolding from Phase 0;
no BankLens code actually reads/writes these stores yet (everything today reads
flat JSON from `data/`). Bring it up once a phase starts actually using them.

```powershell
copy ..\..\.env.example ..\..\.env    # then edit passwords
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps
```

| Service | Port | Role |
|---|---|---|
| Postgres (+pgvector) | 5432 | OLTP system-of-record, audit, agent state, RAG |
| ClickHouse | 8123 / 9000 | time-series serving (candles, metrics) |
| MinIO | 9002 (API) / 9001 (console) | S3-compatible object store (lakehouse) |
| Redis | 6379 | cache / rate-limit / queues |
