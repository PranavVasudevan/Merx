# peer_clustering

Not a separate training path — the real K-Means/silhouette logic for Feature 14
lives in
[`pipelines/transforms/src/banklens_transforms/clustering.py`](../../pipelines/transforms/src/banklens_transforms/clustering.py)
(dependency-free K-Means++ with silhouette-based `k` selection), run via
`banklens_ingestion.clustering_cli` / `scripts/cluster_report.ps1`. See
[`services/feature-services/peer-cluster/README.md`](../../services/feature-services/peer-cluster/README.md)
for the full validated results (real 7-cluster archetypes on the $1B-$250B
population, including the Dime Community Bank misclassification finding).

This directory is reserved for the Phase 3/4 upgrade — swapping in
scikit-learn/GMM plus MLflow experiment tracking — once there's a reason to
outgrow the hand-rolled reference implementation.
