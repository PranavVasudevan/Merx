import { describe, expect, it } from 'vitest';
import { agglomerativeCluster, rowDistance } from './hierarchicalClustering';

describe('rowDistance', () => {
  it('is zero for identical vectors', () => {
    expect(rowDistance([10, 20, 30], [10, 20, 30])).toBe(0);
  });

  it('ignores dimensions where either row is null', () => {
    // Only the second column is comparable (both 50); should be 0, not
    // penalized for the missing first/third columns.
    expect(rowDistance([null, 50, null], [10, 50, 90])).toBe(0);
  });

  it('falls back to a fixed distance when no columns are shared', () => {
    expect(rowDistance([null, null], [null, null])).toBe(100);
  });

  it('grows with the size of the gap', () => {
    const near = rowDistance([50], [55]);
    const far = rowDistance([50], [95]);
    expect(far).toBeGreaterThan(near);
  });
});

describe('agglomerativeCluster', () => {
  it('handles a single row', () => {
    const { order } = agglomerativeCluster([[10, 20]]);
    expect(order).toEqual([0]);
  });

  it('handles an empty population', () => {
    const { order } = agglomerativeCluster([]);
    expect(order).toEqual([]);
  });

  it('places near-identical rows adjacent to each other', () => {
    // Two tight pairs (0,1) and (2,3), far apart from each other.
    const rows = [
      [5, 5],   // 0
      [90, 90], // 1
      [6, 4],   // 2
      [91, 89], // 3
    ];
    const { order } = agglomerativeCluster(rows);
    expect(order).toHaveLength(4);
    // 0 and 2 are the tight low pair; 1 and 3 are the tight high pair.
    // Whichever pair comes first, its two members must be adjacent, and
    // likewise for the other pair.
    const pos = (i: number) => order.indexOf(i);
    expect(Math.abs(pos(0) - pos(2))).toBe(1);
    expect(Math.abs(pos(1) - pos(3))).toBe(1);
  });

  it('produces a permutation of all row indices', () => {
    const rows = Array.from({ length: 12 }, (_, i) => [
      (i * 37) % 100, (i * 13) % 100, (i * 71) % 100,
    ]);
    const { order } = agglomerativeCluster(rows);
    expect([...order].sort((a, b) => a - b)).toEqual(rows.map((_, i) => i));
  });

  it('is stable under rows with entirely missing metrics', () => {
    const rows: (number | null)[][] = [[10, null], [null, 20], [15, 25]];
    const { order } = agglomerativeCluster(rows);
    expect(order).toHaveLength(3);
  });
});
