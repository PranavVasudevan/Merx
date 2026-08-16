import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { EChartsOption } from 'echarts';
import { EChart } from '../components/EChart';
import { baseEChartTheme, tooltipHtml, tooltipStyle } from '../echartsTheme';
import { api } from '../api';
import { categoricalPalette } from '../colors';
import { pct } from '../metricFormat';
import type { NetworkGraphResult } from '../types';
import './NetworkPage.css';

const TOP_N_OPTIONS = [30, 75, 150, 300];

export function NetworkPage() {
  const navigate = useNavigate();
  const [topN, setTopN] = useState(75);
  const [result, setResult] = useState<NetworkGraphResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.network(topN)
      .then((r) => { setResult(r); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [topN]);

  const clusters = useMemo(
    () => [...new Set((result?.nodes ?? []).map((n) => n.cluster_label).filter((c): c is string => !!c))],
    [result],
  );

  const option = useMemo(() => {
    if (!result) return {} as EChartsOption;
    const palette = categoricalPalette();
    const clusterColor = new Map(clusters.map((c, i) => [c, palette[i % palette.length]]));
    const opt: EChartsOption = {
      tooltip: {
        ...tooltipStyle(),
        formatter: (p: unknown) => {
          const node = p as { dataType?: string; data?: { name?: string; value?: number; cluster?: string; fitScore?: number; source?: string; target?: string } };
          if (node.dataType === 'edge') {
            return tooltipHtml(`${node.data?.source} → ${node.data?.target}`, [
              { text: `fit ${pct((node.data?.fitScore ?? 0) * 100, 0)}` },
            ]);
          }
          return tooltipHtml(node.data?.name ?? '', [
            { text: `$${node.data?.value}B · ${node.data?.cluster ?? '—'}` },
          ]);
        },
      },
      legend: { data: clusters, textStyle: { color: baseEChartTheme().textStyle.color, fontSize: 10 }, top: 0 },
      series: [{
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 90, edgeLength: [30, 110], gravity: 0.08 },
        categories: clusters.map((c) => ({ name: c })),
        label: { show: false },
        edgeSymbol: ['none', 'none'],
        lineStyle: { color: 'source', opacity: 0.35, curveness: 0.1 },
        emphasis: { focus: 'adjacency', label: { show: true, fontSize: 10 } },
        data: result.nodes.map((n) => ({
          id: String(n.cert), name: n.name, value: n.assets_b,
          symbolSize: Math.max(6, Math.min(40, Math.sqrt(n.assets_b) * 3)),
          category: n.cluster_label ? clusters.indexOf(n.cluster_label) : 0,
          itemStyle: { color: n.cluster_label ? clusterColor.get(n.cluster_label) : undefined,
                      borderColor: n.is_seed ? baseEChartTheme().tooltipText : undefined,
                      borderWidth: n.is_seed ? 1.5 : 0 },
          cluster: n.cluster_label, cert: n.cert,
        })),
        links: result.edges.map((e) => ({
          source: String(e.source), target: String(e.target),
          fitScore: e.fit_score, lineStyle: { width: 0.5 + e.fit_score * 3 },
        })),
      }],
    };
    return opt;
  }, [result, clusters]);

  const onEvents = useMemo(() => ({
    click: (params: unknown) => {
      const p = params as { dataType?: string; data?: { cert?: number } };
      if (p.dataType === 'node' && p.data?.cert) navigate(`/bank/${p.data.cert}`);
    },
  }), [navigate]);

  return (
    <div className="network-page">
      <div className="panel">
        <h2>M&A fit network</h2>
        <p className="muted network-subtitle">
          The largest banks by assets, connected to their top real M&amp;A-fit
          partners (funding complementarity, business similarity, size, branch
          overlap) — colored by behavioral cluster, sized by assets. Drag nodes,
          click one to open its profile.
        </p>
        <select className="network-select" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
          {TOP_N_OPTIONS.map((n) => <option key={n} value={n}>Top {n} banks by assets</option>)}
        </select>
        {error && <p className="app-banner-error">{error}</p>}
        {loading && (
          <p className="muted network-loading">
            Computing every bank's M&amp;A fit against the whole population — this
            is cached after the first load, but can take up to ~30 seconds cold.
          </p>
        )}
      </div>

      {result && !loading && (
        <div className="panel">
          <p className="muted network-caption">
            {result.nodes.length} banks, {result.edges.length} fit relationships —
            {result.seed_count} seeds by assets plus their top-3 partners.
          </p>
          <EChart
            option={option}
            height={620}
            resetKey={topN}
            ariaLabel="M&A fit force graph"
            onEvents={onEvents}
          />
        </div>
      )}
    </div>
  );
}
