# ADR-0003: Lakehouse table format — Iceberg vs Delta

- **Status:** proposed
- **Date:** 2026-07-23
- **Deciders:** Architecture, Data Platform

## Context
Bronze/Silver/Gold need an open, ACID, time-travelling table format on object
storage that multiple engines (Spark, Trino, DuckDB, Flink) can read. The two
serious options are Apache Iceberg and Delta Lake.

## Decision (pending Phase-0 spike)
Lean **Iceberg** for the sovereign/on-prem posture (engine-agnostic, open catalog
via Nessie/Polaris). Choose **Delta** if we commit to Databricks as the primary
platform (Unity Catalog governance is compelling). Decide after a Phase-0 spike
benchmarking both against our access patterns.

## Consequences
- Either keeps data portable and open; the choice mainly affects catalog/governance tooling.
- Revisit trigger: the Databricks-vs-sovereign decision (see master plan §5.6).
