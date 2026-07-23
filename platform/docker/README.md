# platform/docker — local dev infrastructure

Spins up the stores the platform uses, mirroring production choices at laptop scale.

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

Not required for the Phase-1 vertical slice. Bring it up when you start landing
data into real stores (Phase 1/2).
