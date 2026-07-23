# ADR-0001: Record architecture decisions

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** Architecture

## Context
A multi-year, polyglot, multi-team platform accumulates decisions whose *reasons*
are easily lost. New contributors need to know not just what was chosen but why.

## Decision
We record every significant architectural decision as a lightweight ADR in
`docs/architecture/adr/`, numbered sequentially, using `0000-adr-template.md`.

## Consequences
- Positive: durable rationale; onboarding is faster; reversals are deliberate.
- Trade-off: small authoring overhead per decision.
- Revisit: never — this is the meta-decision.
