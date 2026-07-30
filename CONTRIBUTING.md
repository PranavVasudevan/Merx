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
powershell -File scripts/run_tests.ps1              # full suite (23 files, 135 tests)
python scripts/run_all_tests.py --quiet             # same thing, summary only
python -m ruff check .                              # the lint contract CI enforces
powershell -File scripts/run_vertical_slice.ps1     # live FDIC pull
```

Tests that need landed Bronze data (`data/` is git-ignored and reproducible from
the landing scripts) **skip** rather than fail when it's absent — so a fresh clone
runs green (125 passed, 10 skipped) and CI stays honest instead of either lying or
failing on data it can't have.

## Language conventions

| Language | Lint | Test |
|---|---|---|
| Python | `ruff check .` — **blocking in CI** | each test file is self-contained (stdlib runner, pytest optional) |
| Rust | clippy + rustfmt | cargo test *(no Rust code yet — skeletons only)* |
| TypeScript | `tsc --noEmit` — blocking in CI | vitest *(not yet set up)* |

### Writing PowerShell scripts (`scripts/*.ps1`)
Keep **executable lines pure ASCII**. PowerShell 5.1 decodes `.ps1` files as ANSI,
so a UTF-8 character (an em-dash, say) inside a *string literal* becomes mojibake
and is a hard parse error. Inside `<# … #>` comment blocks it's harmless, which is
why several existing scripts contain them safely — but don't put one in a
`Write-Host "…"`. Use `--` instead of `—` in code.

### The Python lint contract
[`/ruff.toml`](ruff.toml) enables an explicit, minimal rule set (`F`, `E9`, `B`)
rather than ruff's full defaults. That's deliberate: lint was added to an already-
working codebase, and the choice was between adopting every default style opinion
retroactively (mass-rewriting reviewed code) or leaving lint permanently
non-blocking (`|| true`, which catches nothing). The middle path — rules that catch
real defects, enforced for real — is what's here. Widening the set is welcome, but
do it as a deliberate change with the fixes in the same commit.

Match the surrounding code's style; keep comments at the density of the file you're editing.
