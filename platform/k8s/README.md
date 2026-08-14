# platform/k8s — secrets management

## What's here

`base/secrets.yaml` declares three `Secret` resources — **structural placeholders
only**, every `stringData` value is an empty string. They exist so
`kubectl kustomize`/`kubectl apply` render a complete, valid object graph and so
the required key names are documented in one place. **Never fill in real values
in this file or commit it with real data.**

| Secret | Consumed by | Keys | Why |
|---|---|---|---|
| `banklens-db-credentials` | `banklens-bridge` Deployment, `banklens-refresh` CronJob | `DATABASE_URL`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Read by `libs/python/banklens_common/src/banklens_common/db.py`. The bridge uses it for watchlist/agent-run/audit persistence; the refresh CronJob's `filings` stage uses it to store filing-chunk embeddings. `DATABASE_URL` wins over the individual `POSTGRES_*` fields when both are set (matches `.env.example`). |
| `banklens-llm-keys` | `banklens-bridge` Deployment | `GEMINI_API_KEY`, `GEMINI_API_KEY_1..4`, `ANTHROPIC_API_KEY` | Read by `services/agents/src/banklens_agents/{gemini_keys,anthropic_client}.py`, exercised by the bridge's agent endpoints. Only the key(s) matching `BANKLENS_LLM_PROVIDER` need a real value — the default provider (`ollama`) needs none of these. |
| `banklens-market-data-keys` | `banklens-refresh` CronJob | `TIINGO_API_KEY` | Read by `pipelines/ingestion/src/banklens_ingestion/sources/tiingo.py`, used by the DAG's `market_data` stage. |

Each Deployment/CronJob container consumes its secrets via `envFrom.secretRef`
(see `bridge-deployment.yaml` and `refresh-cronjob.yaml`). The web frontend needs
no runtime secrets — its OIDC/API-base config (`VITE_API_BASE`,
`VITE_KEYCLOAK_URL`) is baked in at Docker build time (see
`frontend/apps/web/Dockerfile`), not read at pod runtime, so there is nothing to
inject via Kubernetes.

Non-secret config the bridge reads at runtime (`OIDC_ISSUER`, `OIDC_ROLES_CLAIM`,
`OPA_URL`, `BANKLENS_ALLOWED_ORIGINS`, ...) is deliberately left out of this file
— those aren't credentials, and wiring them up is a ConfigMap concern, not G6's
scope.

## Provisioning path: SealedSecrets

Chosen over External Secrets Operator because ESO needs a live external secrets
backend (Vault, AWS/GCP/Azure secret manager) to point at — every option there
costs money or requires standing up infrastructure this project doesn't have.
SealedSecrets is a single self-hosted controller (free, no external service) that
lets the *encrypted* form of a Secret live safely in git; only the in-cluster
controller can decrypt it. That matches this repo's hard $0-spend rule and its
existing "no cloud dependency beyond what's strictly needed" posture (see the
overlay STUBs' own reasoning for why staging/prod aren't built out yet).

This repo has no live cluster with the controller installed, so the actual
encrypted `SealedSecret` manifests can't be generated or verified here — only the
plaintext-placeholder `Secret` structure above is committed. The steps below are
what an operator runs once a real cluster exists:

1. **Install the controller once per cluster** (cluster-admin, one-time):
   ```
   kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/latest/download/controller.yaml
   ```
   Install the matching `kubeseal` CLI locally (see the same release page).

2. **Create the real Secret locally — never apply or commit it directly:**
   ```
   kubectl create secret generic banklens-db-credentials \
     --namespace=banklens-dev \
     --from-literal=DATABASE_URL='postgresql://user:pass@host/dbname?sslmode=require' \
     --dry-run=client -o yaml > /tmp/banklens-db-credentials.yaml
   ```
   (repeat per secret: `banklens-llm-keys`, `banklens-market-data-keys`, with
   `--from-literal=KEY=value` for each key that needs a real value — omit keys
   you don't use, e.g. skip `ANTHROPIC_API_KEY` if you're not using that provider)

3. **Seal it** — encrypts against the controller's public key, safe to commit:
   ```
   kubeseal --format=yaml --cert=<path-to-controller-public-cert-or-fetched-live> \
     < /tmp/banklens-db-credentials.yaml > platform/k8s/base/sealed/banklens-db-credentials.yaml
   rm /tmp/banklens-db-credentials.yaml
   ```

4. **Swap the placeholder for the sealed one**: replace `secrets.yaml`'s
   corresponding entry in `base/kustomization.yaml`'s `resources` list with the
   new file under `base/sealed/` (or add the sealed files as a small overlay), so
   `kubectl apply -k` creates a real `SealedSecret` object. The controller watches
   it and materializes the real `Secret` in-cluster with the same name the
   Deployments/CronJob already reference — no other manifest change needed.

5. **Rotate** by repeating steps 2-3 and re-applying; the controller updates the
   decrypted Secret in place, and pods pick it up on next restart (`envFrom` is
   not live-reloaded — a rollout restart is required after rotation).
