# config/

Environment-agnostic configuration.

- `sources.yaml` — the **data-source registry**: every source's endpoint, cadence,
  auth, and — critically — its **license tag** and whether it's redistributable.
  Downstream serving/MCP code reads this to decide what may be returned to whom.
- Secrets do **not** live here — see `.env.example` (git-ignored `.env`) and, in
  deployed environments, Vault.
