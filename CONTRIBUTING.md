# Contributing to BankLens

## Ground rules

1. **Gold is the contract.** Features, tools, and agents read from the Gold layer — they never re-derive raw data. If you need a new derived field, add it to Gold with a definition + test, don't compute it ad hoc downstream.
2. **Every transform is tested.** Metric definitions are pinned against real figures (see `pipelines/transforms/tests`). A dbt/Spark reimplementation must reproduce the Python reference exactly.
3. **Provenance always.** Anything landed in Bronze carries source, timestamp, and checksum. Never edit landed bytes — re-land.
4. **Respect data licenses.** Tag every new source in `config/sources.yaml`. Bulk/API before scraping; obey `robots.txt` and rate limits.
5. **Decisions get an ADR.** Architectural choices are recorded under `docs/architecture/adr/`.

## Branching & commits

- Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- Open a PR using the template; CI (lint + tests + data-quality) must pass.

## Local dev

```powershell
powershell -File scripts/run_tests.ps1              # fast, hermetic
powershell -File scripts/run_vertical_slice.ps1     # live FDIC pull
```

## Language conventions

| Language | Lint / format | Test |
|---|---|---|
| Python | ruff + black | pytest |
| Rust | clippy + rustfmt | cargo test |
| TypeScript | eslint + prettier | vitest |

Match the surrounding code's style; keep comments at the density of the file you're editing.
