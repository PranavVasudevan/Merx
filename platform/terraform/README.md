# terraform

Not built yet — genuinely empty, unlike most of `platform/`.

What actually exists today for running this stack: `platform/docker/` (Docker
Compose, dev) and `platform/k8s/` (Kustomize base + per-env overlays — the dev
overlay is deployed and verified end-to-end on a real cluster, see
[`platform/k8s/README.md`](../k8s/README.md)). Neither provisions the underlying
cloud infrastructure (VPC, managed Postgres, cluster nodes) those manifests would
run on — that provisioning step is what this directory is reserved for, on
whichever cloud/on-prem target is chosen (see the project plan). `platform/helm/`
was removed for the same reason it never had content: the real deploy path is
Kustomize, not Helm.
