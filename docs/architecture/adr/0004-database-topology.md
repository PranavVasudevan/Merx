# ADR-0004: Database topology (and why not Cassandra)

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** Architecture, Data Platform

## Context
Different access patterns want different engines: cheap huge analytical storage,
fast per-request queries, high-cardinality time-series serving, and transactional
system-of-record + audit.

## Decision
- **Iceberg/Delta on object storage** — analytical record (Bronze/Silver/Gold).
- **DuckDB (embedded)** — sub-second per-request analytics over Gold, in-process.
- **ClickHouse** — time-series serving (market OHLC/candles, metric history, heatmaps).
- **PostgreSQL (+ pgvector)** — OLTP system-of-record, RBAC, immutable audit, agent state, RAG embeddings.
- **Redis** — cache / rate-limit / ephemeral queues.

**Cassandra: rejected.** It excels at write-heavy, geo-distributed, simple-access
operational loads. Ours is read-heavy analytics with rich ad-hoc queries — the
opposite. ClickHouse + DuckDB + Postgres cover every pattern with less operational
tax. Revisit only if a global high-write real-time tick tier emerges (evaluate
ScyllaDB/ClickHouse-Keeper first).

## Consequences
- Positive: each workload on a fit-for-purpose engine; modest ops footprint.
- Trade-off: several stores to operate; disciplined data contracts keep them coherent.
