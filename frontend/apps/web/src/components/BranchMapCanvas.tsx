import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { geoPath } from 'd3-geo';
import { nationFeature, stateMesh, countyMesh, nationBounds, usAlbersProjection } from '../usTopology';
import { chartColors, onThemeChange, sequentialRamp } from '../colors';
import type { BranchPoint } from '../types';
import './BranchMapCanvas.css';

interface HoverInfo {
  x: number;
  y: number;
  kind: 'branch' | 'aggregate';
  cert?: number;
  name?: string;
  deposits: number;
  fips: string | null;
  count?: number;
}

export interface BranchMapCanvasProps {
  branches: BranchPoint[];
  bankNames: Record<number, string>;
  height?: number;
}

interface ProjectedBranch { x: number; y: number; b: BranchPoint }

/** A county (or, absent a county key, a coarse lat/lon grid cell) worth of branches
 * collapsed into one bubble — count + total deposits, positioned at the mean of its
 * members' projected coordinates. */
interface AggregateBucket { key: string; x: number; y: number; count: number; deposits: number }

interface ViewTransform { k: number; x: number; y: number }

const PADDING_PX = 20;
const HIT_RADIUS_PX = 6;
// How far past the initial fit-to-nation scale the user has to zoom before the map
// switches from county/grid aggregate bubbles to individual branch dots (and starts
// drawing county borders, which are too dense to be legible — or worth the paint
// cost — at national zoom).
const DETAIL_ZOOM_MULT = 2.2;
const MAX_ZOOM_MULT = 40;
const WHEEL_ZOOM_SPEED = 0.0018;

/** [[minX,minY],[maxX,maxY]] of nationBounds -> a {k,x,y} transform that centers and
 * scales the (already-projected) topology/branch coordinate space to fill `width` x
 * `height` with `padding` px of margin, preserving aspect ratio. This is the "zoomed
 * all the way out" transform — wheel/drag adjust k/x/y away from it, and the wheel
 * handler clamps k so the user can never zoom out further than this fit. */
function fitTransform(width: number, height: number, padding: number): ViewTransform {
  const [[minX, minY], [maxX, maxY]] = nationBounds;
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const k = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  return { k, x: (width - spanX * k) / 2 - minX * k, y: (height - spanY * k) / 2 - minY * k };
}

/** Groups branches by county (fips) when known, else by a ~0.5deg lat/lon grid cell
 * — client-side, since GeographyPage already loads the full branch list up front.
 * F9 (backlog): aggregating server-side would cut the payload itself, not just the
 * paint cost; not blocking this map rewrite on a backend change. */
function aggregateBranches(branches: BranchPoint[], projected: ProjectedBranch[]): AggregateBucket[] {
  const groups = new Map<string, AggregateBucket>();
  for (let i = 0; i < branches.length; i++) {
    const b = branches[i];
    const key = b.fips ?? `grid:${Math.round(b.lat * 2)}:${Math.round(b.lon * 2)}`;
    const p = projected[i];
    let g = groups.get(key);
    if (!g) { g = { key, x: 0, y: 0, count: 0, deposits: 0 }; groups.set(key, g); }
    g.x += p.x; g.y += p.y; g.count += 1; g.deposits += b.deposits;
  }
  for (const g of groups.values()) { g.x /= g.count; g.y /= g.count; }
  return [...groups.values()];
}

/**
 * US branch map on a raw <canvas>: real state/county boundaries (us-atlas TopoJSON,
 * see usTopology.ts) drawn via d3-geo's Canvas2D path renderer, branch points
 * projected with the same geoAlbersUsa() instance so both land in one coordinate
 * space with no extra fitting math. Manual wheel-zoom/drag-pan (a {k,x,y} transform
 * applied around the draw calls) rather than d3-zoom's DOM binding — simplest path
 * for a canvas-only widget. Below ~2.2x the initial fit-to-nation scale, individual
 * branches (up to ~76k dots) are collapsed into county/grid aggregate bubbles sized
 * by branch count and colored by total deposits, so national zoom stays cheap to
 * paint; past that threshold it switches to individual dots plus county borders.
 */
export function BranchMapCanvas({ branches, bankNames, height = 460 }: BranchMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointsRef = useRef<ProjectedBranch[]>([]);
  const bucketsRef = useRef<AggregateBucket[]>([]);
  const transformRef = useRef<ViewTransform>({ k: 1, x: 0, y: 0 });
  const fitKRef = useRef(1);
  const userInteractedRef = useRef(false);
  const dragRef = useRef<{ startMx: number; startMy: number; startX: number; startY: number } | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [, setThemeTick] = useState(0);

  useEffect(() => onThemeChange(() => setThemeTick((t) => t + 1)), []);

  // Project every branch once per branches change — usAlbersProjection has a fixed
  // scale/translate (it's not refit per canvas size), so these planar coordinates
  // are stable regardless of zoom/pan/resize; only the view transform below moves
  // them around on screen.
  const projected = useMemo<ProjectedBranch[]>(() => {
    const out: ProjectedBranch[] = [];
    for (const b of branches) {
      const p = usAlbersProjection([b.lon, b.lat]);
      if (p) out.push({ x: p[0], y: p[1], b });
    }
    return out;
  }, [branches]);

  const buckets = useMemo(() => aggregateBranches(branches, projected), [branches, projected]);
  const maxBucketDeposits = useMemo(
    () => buckets.reduce((m, g) => Math.max(m, g.deposits), 0) || 1,
    [buckets],
  );

  useEffect(() => { pointsRef.current = projected; }, [projected]);
  useEffect(() => { bucketsRef.current = buckets; }, [buckets]);

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

    const colors = chartColors();
    const { k, x, y } = transformRef.current;
    const detailed = k >= fitKRef.current * DETAIL_ZOOM_MULT;

    ctx.save();
    ctx.translate(x, y);
    ctx.scale(k, k);

    // Boundaries are drawn with geoPath(null, ctx) — NOT geoPath(usAlbersProjection,
    // ctx) — because states-/counties-albers-10m.json ship geometry that's already
    // projected into Albers-USA planar units (see usTopology.ts). Running it through
    // usAlbersProjection a second time would treat those planar coordinates as
    // degrees and scatter them; an identity geoPath just draws them as-is, which is
    // exactly the space usAlbersProjection([lon,lat]) lands branch points in too.
    const path = geoPath(null, ctx);

    ctx.fillStyle = colors.surface2;
    ctx.beginPath(); path(nationFeature); ctx.fill();

    if (detailed) {
      ctx.strokeStyle = colors.gridline;
      ctx.lineWidth = 0.5 / k;
      ctx.beginPath(); path(countyMesh); ctx.stroke();
    }

    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 1 / k;
    ctx.beginPath(); path(stateMesh); ctx.stroke();

    if (detailed) {
      ctx.fillStyle = colors.blue;
      ctx.globalAlpha = 0.32;
      const r = 1.3 / k;
      for (const p of pointsRef.current) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    } else {
      const ramp = sequentialRamp();
      for (const g of bucketsRef.current) {
        const magnitude = g.deposits / maxBucketDeposits;
        const rampIdx = Math.min(ramp.length - 1, Math.floor(magnitude * ramp.length));
        const rPx = 3 + Math.sqrt(magnitude) * 16; // area ~ deposits, floor so tiny counties stay visible
        ctx.fillStyle = ramp[rampIdx];
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        ctx.arc(g.x, g.y, rPx / k, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    ctx.restore();
  }, [height, maxBucketDeposits]);

  // (Re)fit the view whenever data/size first become available. Once the user has
  // zoomed or panned, resizes no longer snap the view back to the fit — that would
  // discard their navigation every time e.g. a sidebar toggle changes the container
  // width.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function resetView() {
      const width = el!.clientWidth;
      const t = fitTransform(width, height, PADDING_PX);
      fitKRef.current = t.k;
      transformRef.current = t;
    }

    if (!userInteractedRef.current) resetView();
    draw();

    const ro = new ResizeObserver(() => {
      if (!userInteractedRef.current) resetView();
      draw();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [draw, height, branches]);

  // Native (non-passive) wheel listener rather than React's onWheel: React attaches
  // wheel handlers as passive by default, which silently no-ops e.preventDefault()
  // (with a console warning) — the page would scroll out from under the map every
  // time someone tried to zoom it.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      userInteractedRef.current = true;
      const rect = canvas!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { k, x, y } = transformRef.current;
      const factor = Math.exp(-e.deltaY * WHEEL_ZOOM_SPEED);
      const minK = fitKRef.current;
      const maxK = fitKRef.current * MAX_ZOOM_MULT;
      const newK = Math.min(maxK, Math.max(minK, k * factor));
      // Keep the point under the cursor fixed on screen while zooming.
      const worldX = (mx - x) / k, worldY = (my - y) / k;
      transformRef.current = { k: newK, x: mx - worldX * newK, y: my - worldY * newK };
      draw();
    }
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [draw]);

  function onMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const { x, y } = transformRef.current;
    dragRef.current = { startMx: e.clientX - rect.left, startMy: e.clientY - rect.top, startX: x, startY: y };
  }

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (dragRef.current) {
      const d = dragRef.current;
      const dx = mx - d.startMx, dy = my - d.startMy;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) userInteractedRef.current = true;
      transformRef.current = { ...transformRef.current, x: d.startX + dx, y: d.startY + dy };
      setHover(null);
      draw();
      return;
    }

    const { k, x, y } = transformRef.current;
    const worldX = (mx - x) / k, worldY = (my - y) / k;
    const hitRadiusWorld = HIT_RADIUS_PX / k;
    const detailed = k >= fitKRef.current * DETAIL_ZOOM_MULT;

    if (detailed) {
      let best: ProjectedBranch | null = null;
      let bestD2 = hitRadiusWorld * hitRadiusWorld;
      for (const p of pointsRef.current) {
        const dx = p.x - worldX, dy = p.y - worldY;
        const d2 = dx * dx + dy * dy;
        if (d2 < bestD2) { bestD2 = d2; best = p; }
      }
      setHover(best ? {
        x: mx, y: my, kind: 'branch', cert: best.b.cert, deposits: best.b.deposits, fips: best.b.fips,
        name: bankNames[best.b.cert] ?? `CERT ${best.b.cert}`,
      } : null);
    } else {
      let best: AggregateBucket | null = null;
      let bestD2 = Infinity;
      for (const g of bucketsRef.current) {
        const dx = g.x - worldX, dy = g.y - worldY;
        const d2 = dx * dx + dy * dy;
        // Aggregate bubbles have a data-driven radius (up to ~19px on screen) rather
        // than the individual dots' fixed hit radius.
        const rPx = 3 + Math.sqrt(g.deposits / maxBucketDeposits) * 16;
        const rWorld = rPx / k;
        if (d2 < rWorld * rWorld && d2 < bestD2) { bestD2 = d2; best = g; }
      }
      setHover(best ? {
        x: mx, y: my, kind: 'aggregate', deposits: best.deposits, fips: best.key.startsWith('grid:') ? null : best.key,
        count: best.count,
      } : null);
    }
  }

  function onMouseUp() { dragRef.current = null; }

  function onMouseLeave() {
    dragRef.current = null;
    setHover(null);
  }

  function resetZoom() {
    userInteractedRef.current = false;
    const el = containerRef.current;
    if (el) {
      transformRef.current = fitTransform(el.clientWidth, height, PADDING_PX);
      draw();
    }
  }

  return (
    <div className="branch-map-container" ref={containerRef} style={{ height }}>
      <canvas
        ref={canvasRef}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      />
      <button type="button" className="branch-map-reset" onClick={resetZoom}>Reset view</button>
      {hover && hover.kind === 'branch' && (
        <div className="branch-map-tooltip" style={{ left: hover.x + 10, top: hover.y + 10 }}>
          <div className="branch-map-tooltip-name">{hover.name}</div>
          <div className="muted branch-map-tooltip-detail tabular">
            ${(hover.deposits / 1e6).toFixed(1)}M branch deposits
          </div>
          {hover.fips && <div className="muted branch-map-tooltip-detail">FIPS {hover.fips}</div>}
        </div>
      )}
      {hover && hover.kind === 'aggregate' && (
        <div className="branch-map-tooltip" style={{ left: hover.x + 10, top: hover.y + 10 }}>
          <div className="branch-map-tooltip-name">
            {hover.count} branch{hover.count === 1 ? '' : 'es'}
          </div>
          <div className="muted branch-map-tooltip-detail tabular">
            ${(hover.deposits / 1e6).toFixed(1)}M total deposits
          </div>
          {hover.fips ? (
            <div className="muted branch-map-tooltip-detail">FIPS {hover.fips}</div>
          ) : (
            <div className="muted branch-map-tooltip-detail">county unknown — grid cell</div>
          )}
        </div>
      )}
    </div>
  );
}
