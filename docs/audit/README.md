# BankLens Audit — 2026-08-12

Full ground-up architecture, product and analytics review at commit `dd0afe3`.

| File | What it covers |
|---|---|
| [`01-current-state.md`](01-current-state.md) | The idea and intent, all 7 features and how each is implemented, the frontend↔backend seam, the visualisation stack, an effectiveness scorecard, and a free-tier hosting reality check. |
| [`02-client-requirements.md`](02-client-requirements.md) | Simulated client meeting — banker, banking analyst and quant. What each asks for, what all three ask for independently, and the ten things that would stop an investor writing a cheque. |
| [`03-issue-register.md`](03-issue-register.md) | All **95 issues**, each with severity, whether it is fixable / cost-bound / data-bound / inherent, and a mitigation. Plus a 5-wave sequencing plan. |
| [`04-remediation-prompts.md`](04-remediation-prompts.md) | One self-contained, ready-to-paste prompt per issue, keyed by the same ID. Each names the files, states the constraint, and gives acceptance criteria. |

## Issue ID map

| Prefix | Category | Count |
|---|---|---|
| `A` | Deployability, hosting, $0-cost fit | 12 |
| `B` | Data coverage and sourcing | 10 |
| `C` | Analytics and model quality | 15 |
| `D` | Product and workflow gaps | 14 |
| `E` | Visualisation | 15 |
| `F` | Engineering quality | 20 |
| `G` | Security, licensing, governance | 9 |

## The short version

BankLens is a **strong data-engineering project with a shallow quantitative core and
no deployment story.** The medallion architecture is genuinely enforced, the
data-quality disclosure discipline is better than most commercial products, and the
provenance capture is excellent — but it cannot be deployed anywhere (hardcoded
`localhost`), its flagship model is trained on four positives and has never been
backtested, and there is no export, no alerting and no time selector, so it is a
viewer rather than a workflow tool.

**Fix in this order:** make it demonstrable (Wave 1, ~2–3 days) → deployable for $0
(Wave 2, ~1 week) → credible (Wave 3, ~1–2 weeks) → a workflow tool (Wave 4) → a
franchise product (Wave 5). See the sequencing section at the end of
`03-issue-register.md`.

**Highest-leverage single item:** `G9` — surface the provenance that is already
captured. It converts the project's best architectural decision into the one thing no
competitor offers: click any number, see the source URL, the fetch timestamp and the
content checksum.
