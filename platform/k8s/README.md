# k8s

Kustomize base + per-env overlays — Phase 8. **The dev overlay is deployed and
verified end-to-end on a real cluster** (Docker Desktop Kubernetes, v1.36.1).

## Quick start

```powershell
powershell -File scripts/k8s_dev_up.ps1        # build, load data, deploy, wait
```

Then, in a second terminal (see "the localhost:8791 caveat" below):

```powershell
kubectl port-forward -n banklens-dev svc/banklens-bridge 8791:8791
kubectl port-forward -n banklens-dev svc/banklens-web 8080:80
```

…and open <http://localhost:8080>.

## What's deployed

`base/` has the two services that fit the Deployment+Service model: `banklens-bridge`
(REST API, 8791) and `banklens-web` (quant terminal, 80). The MCP server is **not**
here — it speaks JSON-RPC over stdio to a launching client, not over the network, so
a Service would be the wrong shape for it.

`overlays/dev/` adds a `banklens-dev` namespace, a data PVC, and NodePorts.
`overlays/staging|prod/` remain deliberate stubs — real config needs a real target
cluster to validate against, and each stub documents what it would add.

## Three real gotchas this hit, and why the config looks the way it does

Docker Desktop's Kubernetes is **kind-based** (the node is a container named
`desktop-control-plane`), which invalidates several things that work on the classic
Docker Desktop k8s. All three were found by actually deploying, not by reading docs:

**1. `hostPath` cannot reach your files — at all.** The node is a container with its
own overlay filesystem and the Windows host is not mounted into it anywhere
(verified: no `/mnt/c`, no `/run/desktop/mnt/host`, no 9p/virtiofs/drvfs in
`/proc/mounts`). An earlier version of this overlay used a `hostPath` path that was
a documented guess — deploying proved the whole *mechanism* unavailable, not just
the path wrong. Hence the **PVC**, populated by `kubectl cp` from a short-lived
loader pod (the bridge warms its cache at startup, so data must land first). This
also happens to match what staging/prod would really do.

**2. Mutable image tags are silently stale.** The cluster runs its own containerd.
With `imagePullPolicy: IfNotPresent` and a fixed tag like `:local`, rebuilding that
tag in Docker does **not** refresh what the cluster runs — a rebuilt bridge image
containing a newly-required file was silently ignored by the pod. `k8s_dev_up.ps1`
therefore builds a **unique tag per deploy** (`dev-<timestamp>`) and `kubectl set
image`s the Deployments onto it. (Locally-built images *are* otherwise visible to
the cluster — verified — so no `kind load` step is needed.)

**3. NodePort is not reachable from Windows.** NodePorts live on the kind node
container's network and aren't published to the host, so `http://localhost:30080`
does **not** work here (it would on classic Docker Desktop k8s). The NodePorts are
kept because they're valid in-cluster and for other environments, but on this setup
use `kubectl port-forward`.

### The localhost:8791 caveat
The frontend calls the bridge at a hardcoded `http://localhost:8791/api`
(`frontend/apps/web/src/api.ts`). Since NodePorts must be in 30000–32767, the port
the browser needs can only be produced by `port-forward`. Making that URL
configurable is Phase 5+ hardening.

## Verified

- `kubectl kustomize` on base and the dev overlay: clean, zero warnings.
- Deployed for real: both Deployments roll out, pods `1/1 Running`.
- Real data served from the PVC: `get_bank_xray`, `find_ma_matches` (with real
  branch-overlap geo), `get_risk_score` (needs the baked-in `ml/` model card).
- Full UI loaded in a browser against the cluster — every feature rendering real
  FDIC-derived data, zero console errors.

## Teardown

```powershell
kubectl delete namespace banklens-dev
```
