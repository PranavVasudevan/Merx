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

**Honest note on what was verified vs. not, while building this:** `kubectl
kustomize` was run for real and produces the exact manifests shown above (zero
warnings, valid YAML) — that part is proven. The actual `docker build` /
`kubectl apply` / running-pod steps were **not** run in the environment this was
built in — Docker Desktop's daemon needed interactive first-run setup that
couldn't be driven headlessly. Try the steps above yourself; if something doesn't
work exactly as written, it's this last-mile gap, not an untested guess elsewhere
in the manifests.
