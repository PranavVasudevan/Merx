# Security Policy

BankLens handles regulated financial data and is designed to bank-grade controls
(see the master architecture plan, §11). Even in early phases we keep these habits:

## Reporting a vulnerability

Email the maintainers (placeholder: `security@example.org`) — do **not** open a
public issue for security reports. Expect an acknowledgement within 3 business days.

## Baseline controls (enforced as phases land)

- **Secrets** never in git. Use `.env` locally (git-ignored) and Vault in deployed envs.
- **No PII** in URLs, query strings, or logs.
- **Least privilege** everywhere; scrapers may only reach allow-listed hosts.
- **Dependency & container scanning** in CI (Trivy/Grype, `pip-audit`, `cargo audit`).
- **Audit trail** for every MCP tool call and agent action (immutable).
- **Data-license enforcement** at the serving/MCP boundary (`config/sources.yaml`).

## Findings from an actual security pass (Phase 8), and what changed

Real issues found by testing against this codebase, not a generic checklist:

- **Path traversal in `bank_quarters(cert)`** (`services/mcp-server/src/banklens_mcp/data.py`) — reachable from the network via the `diff_filings` MCP tool. A `cert` of `"../../../../.."` was verified live to read `records.json` from *outside* `data/` entirely (confirmed with a planted out-of-tree sentinel file, not just reasoned about). Fixed by coercing `cert` to an actual `int` before it touches a path — a genuine FDIC certificate number is always numeric, so anything else is now rejected rather than silently path-joined. `price_bars(ticker)` had the identical shape; hardened with a path-containment check (the resolved path must stay inside the expected directory) as defense in depth, even though it currently only receives a trusted, crosswalk-derived ticker. Regression tests: `services/mcp-server/tests/test_data.py`.
- **`Access-Control-Allow-Origin: *` on the REST bridge** (`services/api-gateway/src/bridge_server.py`) — this is what made the traversal bug above reachable from *any webpage a user had open in their browser*, not just from a deliberate local client. Replaced with an explicit origin allowlist (the known local frontend origins — Vite dev server, Docker Compose, the K8s dev NodePort), echoed back only on match; every other origin gets no CORS header at all, so a browser blocks it from reading the response.

Neither finding involved secrets or PII — this project only ever serves public
FDIC/SEC/Tiingo data — but "no PII at risk" doesn't mean "no bug," and both are
fixed regardless.

## Supported versions

Pre-GA: only `main` is supported.
