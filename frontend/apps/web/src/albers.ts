// Hand-rolled Albers Equal-Area Conic projection (Snyder, "Map Projections — A
// Working Manual", 1987) — no mapping library, no tile/network calls, works fully
// offline. Standard parallels/meridian match the USGS convention for the
// contiguous US (29.5N / 45.5N standard parallels, 23N origin, 96W central
// meridian). Alaska/Hawaii/territories are NOT inset here (a real Albers-USA inset
// needs boundary data this app doesn't have landed) — see GeographyPage's disclosed
// excluded_non_contiguous count.

const D2R = Math.PI / 180;
const PHI1 = 29.5 * D2R;
const PHI2 = 45.5 * D2R;
const PHI0 = 23 * D2R;
const LAMBDA0 = -96 * D2R;

const N = (Math.sin(PHI1) + Math.sin(PHI2)) / 2;
const C = Math.cos(PHI1) ** 2 + 2 * N * Math.sin(PHI1);
const RHO0 = Math.sqrt(C - 2 * N * Math.sin(PHI0)) / N;

/** Raw projected (x, y) in projection units — y increases NORTHWARD (not screen space). */
export function albersRaw(lat: number, lon: number): [number, number] {
  const phi = lat * D2R;
  const lambda = lon * D2R;
  const rho = Math.sqrt(Math.max(C - 2 * N * Math.sin(phi), 0)) / N;
  const theta = N * (lambda - LAMBDA0);
  return [rho * Math.sin(theta), RHO0 - rho * Math.cos(theta)];
}

export type Projector = (lat: number, lon: number) => [number, number];

/**
 * Build a projector that maps (lat, lon) straight to canvas pixel space, fitted to
 * the bounding box of `points` with `padding` px of margin. Flips the y axis (Albers
 * y grows north; canvas y grows down) and preserves aspect ratio (min of the two
 * axis scales), so the map isn't stretched.
 */
export function fitAlbers(points: { lat: number; lon: number }[], width: number, height: number, padding = 16): Projector {
  if (points.length === 0) {
    return (lat, lon) => albersRaw(lat, lon);
  }
  const projected = points.map((p) => albersRaw(p.lat, p.lon));
  const xs = projected.map((p) => p[0]);
  const ys = projected.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const drawnW = spanX * scale, drawnH = spanY * scale;
  const offsetX = (width - drawnW) / 2;
  const offsetY = (height - drawnH) / 2;
  return (lat: number, lon: number) => {
    const [x, y] = albersRaw(lat, lon);
    return [offsetX + (x - minX) * scale, offsetY + (maxY - y) * scale];
  };
}
