# pipelines/ — the data platform

The medallion pipeline. This is where Phase 1 is functional today.

| Dir | Role | Phase | Language |
|---|---|---|---|
| `ingestion/` | Reference connectors → **Bronze** (raw + provenance) | 1 | Python (stdlib) |
| `transforms/` | **Bronze→Silver→Gold** reference math | 1–2 | Python |
| `dbt/` | Silver/Gold transforms at scale, tested | 2 | SQL (dbt) |
| `dagster/` | Orchestration — software-defined assets, lineage | 1–2 | Python |
| `spark/` | Distributed historical backfills | 2 | PySpark |

**Why Python first?** The reference implementations here let us *see and validate
the math by hand* against real filings before investing in the Rust connector SDK
(`services/ingestion`) and the dbt/Spark transforms. The Python definitions are the
canonical spec; the scaled reimplementations must reproduce their test fixtures.

Run the slice: `powershell -File ../scripts/run_vertical_slice.ps1` (from repo root).
