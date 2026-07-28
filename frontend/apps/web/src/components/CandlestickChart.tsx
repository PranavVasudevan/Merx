import { CandlestickSeries, ColorType, createChart, type IChartApi } from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { CandlesResult, MarketSnapshot } from '../types';
import './CandlestickChart.css';

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
}

export function CandlestickChart({ cert }: { cert: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [candles, setCandles] = useState<CandlesResult | null>(null);
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const colors = chartColors();

  useEffect(() => {
    setError(null);
    setCandles(null);
    setSnapshot(null);
    Promise.all([api.candles(cert), api.marketSnapshot(cert)])
      .then(([c, s]) => { setCandles(c); setSnapshot(s); })
      .catch((e) => setError(String(e.message || e)));
  }, [cert]);

  useEffect(() => {
    if (!containerRef.current || !candles?.bars?.length) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: colors.muted },
      grid: { vertLines: { color: colors.gridline }, horzLines: { color: colors.gridline } },
      width: containerRef.current.clientWidth,
      height: 320,
      timeScale: { borderColor: colors.baseline },
      rightPriceScale: { borderColor: colors.baseline },
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.good, downColor: colors.critical,
      borderUpColor: colors.good, borderDownColor: colors.critical,
      wickUpColor: colors.good, wickDownColor: colors.critical,
    });
    series.setData(candles.bars.map((b) => ({
      time: b.date, open: b.open, high: b.high, low: b.low, close: b.close,
    })));
    chart.timeScale().fitContent();

    const onResize = () => chart.applyOptions({ width: containerRef.current?.clientWidth ?? 600 });
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); chart.remove(); chartRef.current = null; };
  }, [candles, colors]);

  if (error) {
    return (
      <div className="panel">
        <h2>Price chart</h2>
        <p className="muted candle-empty">
          No real price data landed for this bank yet. Market data needs its own free
          Tiingo API key (unlike FDIC/SEC, which need no key at all) — see{' '}
          <code>scripts/land_market_data.ps1</code> in the repo. ({error})
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Price chart{candles ? ` — ${candles.ticker}` : ''}</h2>
      {snapshot && (
        <div className="candle-snapshot">
          <span className="candle-price tabular">${snapshot.close?.toFixed(2)}</span>
          <span className={`tabular ${(snapshot.change_1d_pct ?? 0) >= 0 ? 'candle-up' : 'candle-down'}`}>
            {fmtPct(snapshot.change_1d_pct)} (1d)
          </span>
          <span className="muted tabular">Vol (30d, ann.): {fmtPct(snapshot.volatility_30d_pct)}</span>
          <span className="muted tabular">
            52w: ${snapshot.week52_low?.toFixed(2)} – ${snapshot.week52_high?.toFixed(2)}
          </span>
        </div>
      )}
      <div ref={containerRef} className="candle-container" />
      <p className="muted chart-caption">
        Real EOD data (Tiingo) for {candles?.ticker} — the bank's crosswalk-matched
        ticker (exact/high-confidence match only).
      </p>
    </div>
  );
}
