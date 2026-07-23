# ADR-0002: Polyglot language split

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** Architecture

## Context
Fintech workloads span high-throughput ingestion, deterministic money-math,
distributed transforms, ML, and a rich UI. No single language is best at all of them.

## Decision
Disciplined polyglot — each language owns a domain:
- **Rust** — ingestion/scrapers, deterministic financial engines (stress sim), tick processing.
- **C++** — narrowly scoped to the QuantLib quant kernel (duration/curve math).
- **JVM/Spark + dbt** — distributed medallion transforms at scale.
- **Python** — ML (XGBoost/SHAP), orchestration (Dagster), agents (Claude Agent SDK).
- **TypeScript** — the quant-terminal UI (Lightweight Charts, ECharts, deck.gl).

**Phase-1 pragmatism:** the ingestion/transform *reference* is Python (fast to
learn the data, zero deps); it migrates to Rust/Spark once shapes are understood.

## Consequences
- Positive: right tool per job; strong performance and safety where it matters.
- Trade-off: more toolchains, cross-language CI, hiring breadth.
- Guardrail: do **not** add more languages without an ADR. Go/Rust for gateways — pick one.
