# k8s

Kustomize base + per-env overlays (dev/staging/prod) — Phase 8.

## Status: base + dev overlay real and validated; staging/prod are documented stubs

`base/` deploys the two services that fit the classic Deployment+Service model:
`banklens-bridge` (the REST API, port 8791) and `banklens-web` (the quant terminal,
port 80). The MCP server itself is **not** deployed here — it speaks JSON-RPC over
stdio for a launching client (Claude Code, an agent runtime), not a network `Service`;
containerizing it the same way would force a mismatched deployment pattern.

`overlays/dev/` is real and tested: a `banklens-dev` namespace, a `hostPath` volume
mount for local `data/` (fine for a single-node local cluster; **not** appropriate
for anything beyond that), and a NodePort so the web UI is reachable at a fixed
local port. Validated with `kubectl kustomize` (see below) — genuinely produces
correct manifests, not just written and hoped.

`overlays/staging/` and `overlays/prod/` are deliberately **stubs, not built out** —
writing real staging/prod config without an actual target cluster to validate
against would be speculative, untestable YAML. Each stub documents exactly what it
would add (real PVC instead of hostPath, replicas, Ingress+TLS, NetworkPolicies,
Vault-backed secrets) — see the comments in each file.

## Try it

```powershell
# 1. Build the images (needs Docker Desktop running)
docker build -f services/api-gateway/Dockerfile -t banklens-bridge:local .
docker build -t banklens-web:local frontend/apps/web

# 2. Validate the manifests (no cluster needed)
kubectl kustomize platform/k8s/overlays/dev

# 3. Edit platform/k8s/overlays/dev/bridge-hostpath-patch.yaml — set the hostPath
#    to YOUR machine's real data/ path as the Kubernetes node sees it (Docker
#    Desktop for Windows: check via `kubectl exec` + `ls`, this varies by version)

# 4. Deploy to Docker Desktop's local Kubernetes (Settings -> Kubernetes -> Enable)
kubectl apply -k platform/k8s/overlays/dev
kubectl -n banklens-dev get pods
# then open http://localhost:30080
```

**Status of what's actually been verified:** `kubectl kustomize` was run for real
(zero warnings, valid YAML — proven). Both Docker images were **built and run for
real** via `docker compose -f platform/docker/docker-compose.app.yml up` — a real
bug was found and fixed this way (the bridge image was missing `ml/`, the trained
model card, causing a genuine "Deposit-flight model not trained yet" error in an
otherwise-working container; see the Dockerfile's `COPY ml /app/ml` comment). With
that fix, the full containerized app tier was confirmed working end-to-end: real
Silver/Gold/X-Ray/clustering/stress/M&A/risk-score data served from inside the
bridge container to the containerized frontend, verified in-browser (zero console
errors, `curl` against every endpoint).

**What's still unverified:** the actual `kubectl apply -k overlays/dev` /
running-pod step. Docker Desktop's Kubernetes is a separate opt-in toggle
(Settings → Kubernetes → Enable Kubernetes → Apply & Restart, downloads more images)
that wasn't enabled in this environment — and it's a GUI settings toggle in a
desktop app, not something drivable from a terminal, so this needs the user to
enable it once. The manifests themselves are validated as far as static tooling
goes; only the live-cluster deploy step is unverified.
