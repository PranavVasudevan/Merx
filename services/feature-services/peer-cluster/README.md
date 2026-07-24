# peer-cluster — Feature 14, Peer Group Redefiner (behavioral clustering)

Reclusters banks by how their balance sheet **behaves** (loan mix + funding) rather
than by asset-size buckets, writes a `peer_cluster_id` (+ label) to Gold, and flags
banks whose conventional size label doesn't match their behavioral cluster.

## Status: logic implemented (Phase 1d), service wrapper pending (Phase 3)

Engine: [`pipelines/transforms/src/banklens_transforms/clustering.py`](../../../pipelines/transforms/src/banklens_transforms/clustering.py)
— transparent, dependency-free K-Means (k-means++ init, standardized features) with
silhouette-based validation. The ML-platform phase swaps in scikit-learn + MLflow.
Runner: `banklens_ingestion.clustering_cli` / `scripts/cluster_report.ps1`.

### k selection (honest)
Silhouette peaks at k=2 but that is **degenerate** (one cluster = 91% of banks). Across
k=4–7 silhouette is flat (~0.16–0.19), so we reject degenerate solutions (largest
cluster > 55%) and pick the best remaining — auto-lands on k=7 for the 1,049-bank slice.

### Proven on real data (2026Q1, US banks $1B–$250B)
- 7 behavioral archetypes (CRE-concentrated, C&I/commercial, residential-mortgage, diversified core-funded, diversified high-uninsured, …).
- **Dime Community Bank** clusters into "CRE-concentrated, core-funded" with **Flagstar, Valley National, Bank OZK, Banc of California, Columbia** — real CRE peers — and is flagged **misclassified by size** (behaves like the community-bank cohort despite being regional-sized).
- Community-sized banks scatter across all 7 clusters → asset size ≠ behavior.

### Run
```powershell
powershell -File scripts/cluster_report.ps1 -HighlightCert 6976       # auto k
powershell -File scripts/cluster_report.ps1 -HighlightCert 3511 -K 6  # force k
```

### Next (Phase 3/4)
GMM alternative + stability checks; wrap as gRPC; expose via the `get_peer_cluster`
MCP tool; add growth features (needs multi-quarter history).
