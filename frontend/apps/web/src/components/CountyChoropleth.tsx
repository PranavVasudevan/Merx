import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { geoPath } from 'd3-geo';
import { nationFeature, stateMesh, countyMesh, countyFeatures, nationBounds } from '../usTopology';
import type { CountyFeature } from '../usTopology';
import { chartColors, interpolateRamp, onThemeChange, sequentialRamp } from '../colors';
import './CountyChoropleth.css';

type Bounds = [[number, number], [number, number]];
type Position = number[];

// Bounding box per county, computed once at module load (3,142 counties — cheap,
// same one-time cost as usTopology.ts's own nationBounds) — used both to fit the
// view to a state/merger-impact subset and to bbox-prefilter hit tests so a
// hover/click doesn't have to run full point-in-polygon against all 3,142 shapes.
const FEATURE_BOUNDS: Map<string, Bounds> = new Map(
  countyFeatures.map((f) => [f.id, geoPath().bounds(f) as Bounds]),
);

function boundsOfFips(ids: Iterable<string>): Bounds | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  let any = false;
  for (const id of ids) {
    const b = FEATURE_BOUNDS.get(id);
    if (!b) continue;
    any = true;
    minX = Math.min(minX, b[0][0]); minY = Math.min(minY, b[0][1]);
    maxX = Math.max(maxX, b[1][0]); maxY = Math.max(maxY, b[1][1]);
  }
  return any ? [[minX, minY], [maxX, maxY]] : null;
}

const PADDING_PX = 16;

interface ViewTransform { k: number; x: number; y: number }

function fitTransform(bounds: Bounds, width: number, height: number, padding: number): ViewTransform {
  const [[minX, minY], [maxX, maxY]] = bounds;
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const k = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  return { k, x: (width - spanX * k) / 2 - minX * k, y: (height - spanY * k) / 2 - minY * k };
}

// Even-odd ray-casting point-in-polygon, applied ring by ring so interior rings
// (lake/enclave holes — a handful of real counties, e.g. those wrapping an
// independent city, do have them) correctly punch a hole rather than count as fill.
function ringContains(ring: Position[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function polygonContains(rings: Position[][], x: number, y: number): boolean {
  if (rings.length === 0 || !ringContains(rings[0], x, y)) return false;
  for (let i = 1; i < rings.length; i++) if (ringContains(rings[i], x, y)) return false;
  return true;
}

function featureContains(f: CountyFeature, x: number, y: number): boolean {
  const g = f.geometry;
  if (g.type === 'Polygon') return polygonContains(g.coordinates as Position[][], x, y);
  return (g.coordinates as Position[][][]).some((poly) => polygonContains(poly, x, y));
}

export interface CountyChoroplethProps {
  /** fips -> value to color by (current HHI, or a pro-forma before/after HHI). */
  values: Map<string, number>;
  /** fips at/crossing the concentrated threshold — drawn with a distinct outline. */
  highlighted: Set<string>;
  /** Upper end of the color scale — pass the observed max in `values`, not an invented cap. */
  colorDomainMax: number;
  /** 2-digit Census state FIPS prefix (state filter) — restricts which counties render
   *  and, absent `focusFips`, what the view fits to. Derived by the caller from a
   *  returned county's own `fips` (its first 2 digits), not a separate lookup table. */
  stateFipsPrefix?: string | null;
  /** When set (the pro-forma before/after view), the view fits to these counties'
   *  combined bounds instead of the state filter / whole nation — the merger's
   *  affected counties can span states the dropdown alone wouldn't show. */
  focusFips?: Set<string> | null;
  selectedFips: string | null;
  onSelect: (fips: string | null) => void;
  /** County display name for the hover tooltip — falls back to the topology's own name. */
  labelFor?: (fips: string) => string | null;
  height?: number;
}

interface HoverInfo { x: number; y: number; fips: string; name: string }

/**
 * E8 — county-level choropleth on the same raw-canvas + d3-geo pattern
 * BranchMapCanvas uses (see usTopology.ts): real Census county polygons
 * (us-atlas TopoJSON, pre-projected Albers-USA, no map tiles/API key),
 * filled by a caller-supplied value (HHI, or a pro-forma before/after HHI)
 * via `interpolateRamp` over `sequentialRamp()` — no invented colors. No
 * wheel-zoom/pan (unlike BranchMapCanvas): the state filter and pro-forma
 * "focus" already say what should be in view, so the fit is recomputed
 * directly from that rather than needing manual navigation.
 */
export function CountyChoropleth({
  values, highlighted, colorDomainMax, stateFipsPrefix, focusFips, selectedFips, onSelect, labelFor, height = 480,
}: CountyChoroplethProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const transformRef = useRef<ViewTransform>({ k: 1, x: 0, y: 0 });
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [, setThemeTick] = useState(0);

  useEffect(() => onThemeChange(() => setThemeTick((t) => t + 1)), []);

  const visibleFeatures = useMemo(
    () => (stateFipsPrefix ? countyFeatures.filter((f) => f.id.startsWith(stateFipsPrefix)) : countyFeatures),
    [stateFipsPrefix],
  );

  const bounds = useMemo<Bounds>(() => {
    if (focusFips && focusFips.size > 0) return boundsOfFips(focusFips) ?? (nationBounds as Bounds);
    if (stateFipsPrefix) return boundsOfFips(visibleFeatures.map((f) => f.id)) ?? (nationBounds as Bounds);
    return nationBounds as Bounds;
  }, [focusFips, stateFipsPrefix, visibleFeatures]);

  const draw = useCallback(() => {
    const el = containerRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    const width = el.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const t = fitTransform(bounds, width, height, PADDING_PX);
    transformRef.current = t;
    const colors = chartColors();
    const ramp = sequentialRamp();

    ctx.save();
    ctx.translate(t.x, t.y);
    ctx.scale(t.k, t.k);

    // path draws directly onto ctx in the pre-projected planar space the topology
    // ships in — identity geoPath, same reasoning as BranchMapCanvas.
    const path = geoPath(null, ctx);

    ctx.fillStyle = colors.surface2;
    ctx.beginPath(); path(nationFeature); ctx.fill();

    for (const f of visibleFeatures) {
      const v = values.get(f.id);
      ctx.fillStyle = v == null
        ? colors.surface2
        : interpolateRamp(ramp, colorDomainMax > 0 ? v / colorDomainMax : 0);
      ctx.beginPath();
      path(f);
      ctx.fill();
    }

    // Shared county borders as one deduped mesh (usTopology.ts's countyMesh) rather
    // than stroking each of the ~3,142 filled polygons a second time.
    ctx.strokeStyle = colors.gridline;
    ctx.lineWidth = 0.5 / t.k;
    ctx.beginPath(); path(countyMesh); ctx.stroke();

    if (highlighted.size > 0) {
      ctx.strokeStyle = colors.critical;
      ctx.lineWidth = 1.5 / t.k;
      for (const f of visibleFeatures) {
        if (!highlighted.has(f.id)) continue;
        ctx.beginPath(); path(f); ctx.stroke();
      }
    }

    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 1 / t.k;
    ctx.beginPath(); path(stateMesh); ctx.stroke();

    if (selectedFips) {
      const sel = visibleFeatures.find((f) => f.id === selectedFips)
        ?? countyFeatures.find((f) => f.id === selectedFips);
      if (sel) {
        ctx.strokeStyle = colors.text;
        ctx.lineWidth = 2.5 / t.k;
        ctx.beginPath(); path(sel); ctx.stroke();
      }
    }

    ctx.restore();
  }, [bounds, visibleFeatures, values, highlighted, colorDomainMax, selectedFips, height]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    draw();
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    return () => ro.disconnect();
  }, [draw]);

  const featureAt = useCallback((mx: number, my: number): CountyFeature | null => {
    const { k, x, y } = transformRef.current;
    const worldX = (mx - x) / k;
    const worldY = (my - y) / k;
    for (const f of visibleFeatures) {
      const b = FEATURE_BOUNDS.get(f.id);
      if (!b) continue;
      if (worldX < b[0][0] || worldX > b[1][0] || worldY < b[0][1] || worldY > b[1][1]) continue;
      if (featureContains(f, worldX, worldY)) return f;
    }
    return null;
  }, [visibleFeatures]);

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const f = featureAt(mx, my);
    if (!f) { setHover(null); return; }
    const name = labelFor?.(f.id) ?? f.properties?.name ?? f.id;
    setHover({ x: mx, y: my, fips: f.id, name });
  }

  function onMouseLeave() { setHover(null); }

  function onClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const f = featureAt(e.clientX - rect.left, e.clientY - rect.top);
    onSelect(f ? (f.id === selectedFips ? null : f.id) : null);
  }

  const hoverValue = hover ? values.get(hover.fips) : undefined;

  return (
    <div className="county-choropleth-container" ref={containerRef} style={{ height }}>
      <canvas
        ref={canvasRef}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
        onClick={onClick}
      />
      {hover && (
        <div className="county-choropleth-tooltip" style={{ left: hover.x + 10, top: hover.y + 10 }}>
          <div className="county-choropleth-tooltip-name">{hover.name}</div>
          <div className="muted county-choropleth-tooltip-detail tabular">
            {hoverValue != null ? `HHI ${hoverValue.toFixed(0)}` : 'no deposit data'}
          </div>
          {highlighted.has(hover.fips) && (
            <div className="county-choropleth-tooltip-flag">at/above concentrated threshold</div>
          )}
        </div>
      )}
    </div>
  );
}
