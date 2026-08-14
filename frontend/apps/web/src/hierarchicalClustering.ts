/**
 * Agglomerative hierarchical clustering over percentile-vector rows, for the
 * heatmap's "clustered order" — a plain-TS implementation rather than a new
 * dependency, since the population sizes here (tens to a couple hundred rows,
 * ~10-20 metric columns) make the naive O(n^3) merge loop trivial (n=100 is
 * 1e6 distance comparisons, well under a frame).
 *
 * Algorithm: UPGMA (average-linkage) agglomerative clustering.
 *   1. Build a full pairwise distance matrix (Euclidean, over whatever metric
 *      columns both rows have a real value for — see `rowDistance`).
 *   2. Repeatedly merge the closest pair of clusters, recording each merge as
 *      a binary tree node with a height (the merge distance) — that tree is
 *      the dendrogram.
 *   3. Read the tree's leaves left-to-right to get the "clustered order":
 *      adjacent leaves are the most similar pairs, and larger structural
 *      blocks (e.g. "thin-capital, high-NPL banks") become visually
 *      contiguous bands in the heatmap instead of being scattered across a
 *      single sort key.
 *
 * Complexity: O(n^2) pairs each iteration, O(n) merges -> O(n^3) time,
 * O(n^2) space for the distance matrix. Fine up to a few hundred rows; the
 * heatmap page caps `topN` at 100.
 */

export interface ClusterLeaf {
  kind: 'leaf';
  index: number;
}

export interface ClusterNode {
  kind: 'node';
  left: ClusterTree;
  right: ClusterTree;
  height: number;
  /** Row indices covered by this subtree, in dendrogram (leaf) order. */
  order: number[];
}

export type ClusterTree = ClusterLeaf | ClusterNode;

/**
 * Euclidean distance between two percentile vectors, computed only over
 * dimensions where BOTH rows have a non-null value — a bank missing one
 * metric shouldn't be treated as maximally different from everyone else on
 * that single column. Falls back to the max possible distance (100 per
 * shared dimension, scaled) if the rows share no comparable metric at all,
 * so they sort apart rather than crash the merge.
 */
export function rowDistance(a: (number | null)[], b: (number | null)[]): number {
  let sumSq = 0;
  let n = 0;
  for (let i = 0; i < a.length; i++) {
    const av = a[i], bv = b[i];
    if (av === null || bv === null || av === undefined || bv === undefined) continue;
    const d = av - bv;
    sumSq += d * d;
    n++;
  }
  if (n === 0) return 100; // no comparable columns — treat as fully dissimilar
  // Normalize by number of shared dimensions so a row missing a few metrics
  // isn't penalized just for having fewer terms in the sum.
  return Math.sqrt(sumSq / n);
}

/**
 * Average-linkage (UPGMA) agglomerative clustering. Returns the dendrogram
 * root plus the flat leaf order (row indices, left-to-right).
 *
 * `rows.length` must be >= 1. A single row returns a single leaf.
 */
export function agglomerativeCluster(rows: (number | null)[][]): { tree: ClusterTree; order: number[] } {
  const n = rows.length;
  if (n === 0) return { tree: { kind: 'leaf', index: 0 }, order: [] };
  if (n === 1) return { tree: { kind: 'leaf', index: 0 }, order: [0] };

  // Full pairwise distance matrix, O(n^2).
  const dist: number[][] = Array.from({ length: n }, () => new Array(n).fill(0));
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = rowDistance(rows[i], rows[j]);
      dist[i][j] = d;
      dist[j][i] = d;
    }
  }

  // Active clusters: id -> { tree, size, members (original row indices) }.
  type Active = { tree: ClusterTree; size: number; members: number[] };
  const active = new Map<number, Active>();
  for (let i = 0; i < n; i++) {
    active.set(i, { tree: { kind: 'leaf', index: i }, size: 1, members: [i] });
  }
  // Cluster-to-cluster average-linkage distance, keyed by "a,b" (a<b), lazily
  // derived from the original row distance matrix each merge — O(n) per pair
  // lookup would be wasteful to cache exactly, so instead we recompute a
  // cluster pair's average distance on demand from its member lists. With
  // n <= ~100 this stays cheap.
  function clusterDistance(x: Active, y: Active): number {
    let sum = 0;
    for (const i of x.members) {
      for (const j of y.members) sum += dist[i][j];
    }
    return sum / (x.members.length * y.members.length);
  }

  let nextId = n;
  let ids = [...active.keys()];
  let mergeHeight = 0;

  while (ids.length > 1) {
    let bestI = -1, bestJ = -1, bestD = Infinity;
    for (let a = 0; a < ids.length; a++) {
      for (let b = a + 1; b < ids.length; b++) {
        const ca = active.get(ids[a])!;
        const cb = active.get(ids[b])!;
        const d = clusterDistance(ca, cb);
        if (d < bestD) { bestD = d; bestI = a; bestJ = b; }
      }
    }
    const idA = ids[bestI], idB = ids[bestJ];
    const ca = active.get(idA)!, cb = active.get(idB)!;
    // Monotone dendrogram heights (each merge at least as high as the last)
    // keep the tree visually sane even if a later merge's raw average
    // distance dips slightly below an earlier one.
    mergeHeight = Math.max(mergeHeight, bestD);
    const order = [...ca.tree.kind === 'leaf' ? [ca.tree.index] : ca.tree.order,
      ...cb.tree.kind === 'leaf' ? [cb.tree.index] : cb.tree.order];
    const merged: ClusterNode = { kind: 'node', left: ca.tree, right: cb.tree, height: mergeHeight, order };
    const id = nextId++;
    active.delete(idA);
    active.delete(idB);
    active.set(id, { tree: merged, size: ca.size + cb.size, members: [...ca.members, ...cb.members] });
    ids = [...active.keys()];
  }

  const root = active.get(ids[0])!.tree;
  const order = root.kind === 'leaf' ? [root.index] : root.order;
  return { tree: root, order };
}
