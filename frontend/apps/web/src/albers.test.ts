import { describe, expect, it } from 'vitest';
import { albersRaw, fitAlbers } from './albers';

describe('albersRaw', () => {
  it('maps the projection origin (23N, 96W) to (0, 0) by construction', () => {
    // The origin latitude/central meridian are exactly PHI0/LAMBDA0, so
    // rho == RHO0 and theta == 0 — this isn't an arbitrary fixture, it falls
    // straight out of the Snyder formulas the module implements.
    const [x, y] = albersRaw(23, -96);
    expect(x).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(0, 9);
  });

  it('moves east (higher longitude) to a positive x', () => {
    const [x] = albersRaw(23, -90);
    expect(x).toBeGreaterThan(0);
  });

  it('moves west (lower longitude) to a negative x', () => {
    const [x] = albersRaw(23, -100);
    expect(x).toBeLessThan(0);
  });

  it('moves north (higher latitude) to a greater y (y grows northward)', () => {
    const [, ySouth] = albersRaw(25, -96);
    const [, yNorth] = albersRaw(40, -96);
    expect(yNorth).toBeGreaterThan(ySouth);
  });

  it('is finite for latitudes across the full valid range, not just the contiguous US', () => {
    for (const lat of [-90, -45, 0, 45, 89.9]) {
      const [x, y] = albersRaw(lat, -96);
      expect(Number.isFinite(x)).toBe(true);
      expect(Number.isFinite(y)).toBe(true);
    }
  });

  it('propagates NaN for a NaN/missing coordinate instead of throwing', () => {
    expect(() => albersRaw(NaN, -96)).not.toThrow();
    const [x, y] = albersRaw(NaN, -96);
    expect(Number.isNaN(x)).toBe(true);
    expect(Number.isNaN(y)).toBe(true);
  });
});

describe('fitAlbers', () => {
  it('falls back to the raw (unfitted) projector when given no points', () => {
    const projector = fitAlbers([], 800, 600);
    expect(projector(23, -96)).toEqual(albersRaw(23, -96));
  });

  it('fits a single point within the canvas bounds, not off-canvas', () => {
    // spanX/spanY are forced to 1 (the `|| 1` fallback) when min===max, and the
    // single point sits at (x - minX, maxY - y) = (0, 0) within that span, i.e. at
    // the scaled-box's origin corner (offsetX, offsetY) — NOT the canvas center,
    // since the 1x1 unit box's aspect ratio generally doesn't match the canvas's.
    const width = 800, height = 600, padding = 16;
    const projector = fitAlbers([{ lat: 40, lon: -100 }], width, height, padding);
    const [x, y] = projector(40, -100);
    expect(x).toBeGreaterThanOrEqual(padding - 0.01);
    expect(x).toBeLessThanOrEqual(width - padding + 0.01);
    expect(y).toBeGreaterThanOrEqual(padding - 0.01);
    expect(y).toBeLessThanOrEqual(height - padding + 0.01);
  });

  it('keeps every projected point within the canvas bounds', () => {
    const points = [
      { lat: 47.6, lon: -122.3 }, // Seattle
      { lat: 25.8, lon: -80.2 },  // Miami
      { lat: 42.4, lon: -71.1 },  // Boston
      { lat: 34.0, lon: -118.2 }, // Los Angeles
    ];
    const width = 900, height = 500, padding = 16;
    const projector = fitAlbers(points, width, height, padding);
    for (const p of points) {
      const [x, y] = projector(p.lat, p.lon);
      expect(x).toBeGreaterThanOrEqual(padding - 0.01);
      expect(x).toBeLessThanOrEqual(width - padding + 0.01);
      expect(y).toBeGreaterThanOrEqual(padding - 0.01);
      expect(y).toBeLessThanOrEqual(height - padding + 0.01);
    }
  });

  it('produces NaN (not a throw) when projecting a NaN coordinate through a fitted projector', () => {
    const projector = fitAlbers([{ lat: 40, lon: -100 }], 800, 600);
    expect(() => projector(NaN, NaN)).not.toThrow();
    const [x, y] = projector(NaN, NaN);
    expect(Number.isNaN(x)).toBe(true);
    expect(Number.isNaN(y)).toBe(true);
  });
});
