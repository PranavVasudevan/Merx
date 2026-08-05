import { useEffect, useRef, useState } from 'react';
import { fitAlbers } from '../albers';
import { chartColors, onThemeChange } from '../colors';
import type { BranchPoint } from '../types';
import './BranchMapCanvas.css';

interface HoverInfo {
  x: number;
  y: number;
  cert: number;
  name: string;
  deposits: number;
  fips: string | null;
}

export interface BranchMapCanvasProps {
  branches: BranchPoint[];
  bankNames: Record<number, string>;
  height?: number;
}

const HIT_RADIUS_PX = 6;

/**
 * Raw <canvas> US branch map via a hand-rolled Albers projection (albers.ts) — no
 * mapping library, no tile/network calls. Dots are drawn with low alpha so overlapping
 * branches in dense metros compound into a real density visualization rather than
 * needing a separate heatmap layer.
 */
export function BranchMapCanvas({ branches, bankNames, height = 460 }: BranchMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointsRef = useRef<{ x: number; y: number; b: BranchPoint }[]>([]);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [, setThemeTick] = useState(0);

  useEffect(() => onThemeChange(() => setThemeTick((t) => t + 1)), []);

  useEffect(() => {
    const el = containerRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;

    function draw() {
      const width = el!.clientWidth;
      const dpr = window.devicePixelRatio || 1;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      const ctx = canvas!.getContext('2d');
      if (!ctx) return;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      const colors = chartColors();
      const project = fitAlbers(branches, width, height, 20);
      const pts = branches.map((b) => {
        const [x, y] = project(b.lat, b.lon);
        return { x, y, b };
      });
      pointsRef.current = pts;

      ctx.fillStyle = colors.blue;
      ctx.globalAlpha = 0.32;
      for (const p of pts) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.3, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(el);
    return () => ro.disconnect();
  }, [branches, height]);

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best: { x: number; y: number; b: BranchPoint } | null = null;
    let bestD2 = HIT_RADIUS_PX * HIT_RADIUS_PX;
    for (const p of pointsRef.current) {
      const dx = p.x - mx, dy = p.y - my;
      const d2 = dx * dx + dy * dy;
      if (d2 < bestD2) { bestD2 = d2; best = p; }
    }
    if (best) {
      setHover({
        x: mx, y: my, cert: best.b.cert, deposits: best.b.deposits, fips: best.b.fips,
        name: bankNames[best.b.cert] ?? `CERT ${best.b.cert}`,
      });
    } else {
      setHover(null);
    }
  }

  return (
    <div className="branch-map-container" ref={containerRef} style={{ height }}>
      <canvas
        ref={canvasRef}
        onMouseMove={onMouseMove}
        onMouseLeave={() => setHover(null)}
      />
      {hover && (
        <div className="branch-map-tooltip" style={{ left: hover.x + 10, top: hover.y + 10 }}>
          <div className="branch-map-tooltip-name">{hover.name}</div>
          <div className="muted branch-map-tooltip-detail tabular">
            ${(hover.deposits / 1e6).toFixed(1)}M branch deposits
          </div>
          {hover.fips && <div className="muted branch-map-tooltip-detail">FIPS {hover.fips}</div>}
        </div>
      )}
    </div>
  );
}
