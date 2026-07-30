<#
.SYNOPSIS
    Deploy BankLens to a local Kubernetes cluster (Docker Desktop) and populate it
    with your landed data.

.DESCRIPTION
    Handles the ordering that makes this actually work:
      1. build the two images (the cluster shares Docker Desktop's image store)
      2. create the namespace + data PVC
      3. run a short-lived loader pod and `kubectl cp` the landed data into the PVC
         -- the bridge warms its population cache at STARTUP, so data must be in
         place before it runs
      4. deploy the app and wait for it to be ready

    Why a PVC and not hostPath: Docker Desktop's Kubernetes is kind-based; the node
    is a container with its own filesystem and the Windows host is not mounted into
    it (verified live). hostPath cannot see your `data/` directory here at all.

    Prerequisites: Docker Desktop running with Kubernetes enabled, and data already
    landed locally (scripts/run_vertical_slice.ps1, crosswalk.ps1, land_sod.ps1...).

.EXAMPLE
    powershell -File scripts/k8s_dev_up.ps1
#>
param(
    [switch]$SkipBuild,
    [string]$DockerBin = "C:\Users\gouri\AppData\Local\Programs\DockerDesktop\resources\bin"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (Test-Path $DockerBin) { $env:PATH = "$DockerBin;" + $env:PATH }

$ns      = "banklens-dev"
$overlay = Join-Path $repo "platform/k8s/overlays/dev"
$dataDir = Join-Path $repo "data"

if (-not (Test-Path (Join-Path $dataDir "bronze/source=fdic/population/repdte=20260331/records.json"))) {
    Write-Error "No landed population data in $dataDir. Run the landing scripts first (e.g. scripts/run_vertical_slice.ps1)."
}

# A UNIQUE tag per deploy. This is not cosmetic: Docker Desktop's Kubernetes runs
# its own containerd, and with a mutable tag like ":local" plus
# imagePullPolicy: IfNotPresent, the cluster keeps serving the image it already
# cached even after you rebuild that same tag in Docker. Caught live -- a rebuilt
# bridge image containing a required file was silently ignored by the running pod.
# A fresh tag makes the image reference genuinely new, so there's nothing to reuse.
$tag = "dev-" + (Get-Date -Format "yyyyMMdd-HHmmss")

if (-not $SkipBuild) {
    Write-Host "[1/5] Building images (tag: $tag)..." -ForegroundColor Cyan
    Push-Location $repo
    try {
        docker build -f services/api-gateway/Dockerfile -t "banklens-bridge:$tag" .
        if ($LASTEXITCODE -ne 0) { throw "bridge image build failed" }
        docker build -t "banklens-web:$tag" frontend/apps/web
        if ($LASTEXITCODE -ne 0) { throw "web image build failed" }
    } finally { Pop-Location }
} else {
    # Reuse whatever :local currently is. Fine for iterating on manifests, but it
    # will NOT pick up code changes -- see the stale-image note above.
    Write-Host "[1/5] Skipping image build (-SkipBuild) -- reusing :local tags" -ForegroundColor DarkGray
    $tag = "local"
}

Write-Host "[2/5] Creating namespace + data PVC..." -ForegroundColor Cyan
kubectl apply -f (Join-Path $overlay "namespace.yaml") | Out-Null
kubectl apply -n $ns -f (Join-Path $overlay "data-pvc.yaml") | Out-Null

Write-Host "[3/5] Loading data into the PVC (bridge needs it at startup)..." -ForegroundColor Cyan
kubectl delete pod banklens-data-loader -n $ns --ignore-not-found=true | Out-Null
kubectl apply -n $ns -f (Join-Path $overlay "data-loader.yaml") | Out-Null
kubectl wait --for=condition=Ready pod/banklens-data-loader -n $ns --timeout=120s | Out-Null

# Copy only what the bridge actually reads -- not the whole 31MB tree (agent_runs,
# gold/ outputs and audit logs are runtime artifacts, not inputs).
#
# Run from INSIDE data/ and use relative paths: `kubectl cp` treats a colon as the
# pod/path separator, so a Windows absolute path like C:\... is parsed as
# pod "C" + path "\..." and fails with "one of src or dest must be a local file
# specification". Relative paths have no colon, so they sidestep it entirely.
# Clear the target dirs first: `kubectl cp src pod:/data/src` NESTS (creating
# /data/bronze/bronze) when the destination already exists, so re-running this
# script would silently duplicate the data instead of refreshing it.
kubectl exec -n $ns banklens-data-loader -- sh -c "rm -rf /data/bronze /data/silver" | Out-Null

Push-Location $dataDir
try {
    foreach ($sub in @("bronze", "silver")) {
        if (Test-Path $sub) {
            Write-Host "      copying data/$sub ..." -ForegroundColor DarkGray
            kubectl cp $sub "${ns}/banklens-data-loader:/data/$sub"
            if ($LASTEXITCODE -ne 0) { throw "kubectl cp of data/$sub failed" }
        }
    }
} finally { Pop-Location }
kubectl exec -n $ns banklens-data-loader -- sh -c "echo '      loaded:' && du -sh /data/* 2>/dev/null"
kubectl delete pod banklens-data-loader -n $ns --ignore-not-found=true --wait=$true | Out-Null

Write-Host "[4/5] Deploying the app..." -ForegroundColor Cyan
kubectl apply -k $overlay | Out-Null
# Point the Deployments at THIS build's unique tag (the manifests carry ":local" as
# a placeholder). Doing it here keeps the committed YAML static while still
# guaranteeing each deploy runs the image we just built.
kubectl set image deployment/banklens-bridge bridge="banklens-bridge:$tag" -n $ns | Out-Null
kubectl set image deployment/banklens-web web="banklens-web:$tag" -n $ns | Out-Null
kubectl rollout status deployment/banklens-bridge -n $ns --timeout=180s
kubectl rollout status deployment/banklens-web -n $ns --timeout=180s

Write-Host "[5/5] Ready." -ForegroundColor Green
kubectl get pods,svc -n $ns
Write-Host ""
Write-Host "  Quant terminal : http://localhost:30080" -ForegroundColor Green
Write-Host "  Bridge API     : http://localhost:30791/api/health  (direct NodePort, for curl)" -ForegroundColor Green
Write-Host ""
Write-Host "  NOTE: the frontend calls the bridge at a HARDCODED http://localhost:8791," -ForegroundColor Yellow
Write-Host "        so for the browser UI to load data you must also run, in another terminal:" -ForegroundColor Yellow
Write-Host "          kubectl port-forward -n $ns svc/banklens-bridge 8791:8791" -ForegroundColor Yellow
Write-Host "        (making that URL configurable is Phase 5+ hardening -- see frontend README)" -ForegroundColor DarkGray
