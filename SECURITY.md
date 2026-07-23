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

## Supported versions

Pre-GA: only `main` is supported.
