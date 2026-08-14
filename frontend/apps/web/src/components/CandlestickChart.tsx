import {
  CandlestickSeries, ColorType, createChart, HistogramSeries, LineSeries, PriceScaleMode,
  type IChartApi, type MouseEventParams,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { chartColors, onThemeChange } from '../colors';
import { BankSearch } from './BankSearch';
import type { CandlesResult, MarketCoverageResult, MarketSnapshot, PriceBar } from '../types';
import './CandlestickChart.css';

// Wide enough window (~3 trading years) that a 200-day SMA has a real lead-in
// and the 1Y/All range buttons have something to show — the old 180-day
// default only just covered the 6M button.
const FETCH_LIMIT_DAYS = 760;
const SMA_PERIODS = [50, 200] as const;

type RangeSel = '1M' | '3M' | '6M' | '1Y' | 'All';
const RANGE_DAYS: Record<Exclude<RangeSel, 'All'>, number> = { '1M': 30, '3M': 91, '6M': 182, '1Y': 365 };

interface ComparePeer { cert: number; name: string }
interface CrosshairInfo { date: string; open: number; high: number; low: number; close: number; volume: number | null }

function fmtPct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function fmtVolume(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

/** First bar date on/after "N days before the last bar" — used both to set the
    visible time range and to pick the base bar the comparison series indexes to 100. */
function rangeStartDate(bars: PriceBar[], sel: Exclude<RangeSel, 'All'>): string {
  const last = new Date(`${bars[bars.length - 1].date}T00:00:00Z`);
  const cutoff = new Date(last);
  cutoff.setUTCDate(cutoff.getUTCDate() - RANGE_DAYS[sel]);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return bars.find((b) => b.date >= cutoffStr)?.date ?? bars[0].date;
}

/** Trailing simple moving average, as sparse {time, value} points (no point
    before there's a full window — lightweight-charts just skips the gap). */
function sma(bars: PriceBar[], period: number): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].date, value: sum / period });
  }
  return out;
}

export function CandlestickChart({ cert }: { cert: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [candles, setCandles] = useState<CandlesResult | null>(null);
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [coverage, setCoverage] = useState<MarketCoverageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [themeTick, setThemeTick] = useState(0);
  const [rangeSel, setRangeSel] = useState<RangeSel>('6M');
  const [logScale, setLogScale] = useState(false);
  const [comparePeer, setComparePeer] = useState<ComparePeer | null>(null);
  const [compareBars, setCompareBars] = useState<PriceBar[] | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [crosshair, setCrosshair] = useState<CrosshairInfo | null>(null);
  const colors = chartColors();

  // lightweight-charts is imperative canvas like ECharts (see EChart.tsx) — it
  // won't pick up new colors from a React re-render on its own, so a skin/OS
  // theme flip needs to force the init effect below to re-run and rebuild it.
  useEffect(() => onThemeChange(() => setThemeTick((t) => t + 1)), []);

  useEffect(() => {
    setError(null);
    setCandles(null);
    setSnapshot(null);
    Promise.all([api.candles(cert, FETCH_LIMIT_DAYS), api.marketSnapshot(cert)])
      .then(([c, s]) => { setCandles(c); setSnapshot(s); })
      .catch((e) => setError(String(e.message || e)));
    // Own catch: market_cli.py's persisted-cursor landing (see that module's
    // docstring) means coverage grows across scheduled runs rather than all
    // at once — a bank not covered YET isn't an error, so this failing
    // silently degrades to no coverage note rather than blocking the chart.
    api.marketCoverage().then(setCoverage).catch(() => setCoverage(null));
    // A new bank means any comparison picked for the old one no longer applies.
    setComparePeer(null);
  }, [cert]);

  useEffect(() => {
    if (!comparePeer) { setCompareBars(null); setCompareError(null); return; }
    let cancelled = false;
    setCompareError(null);
    api.candles(comparePeer.cert, FETCH_LIMIT_DAYS)
      .then((r) => { if (!cancelled) setCompareBars(r.bars); })
      .catch((e) => { if (!cancelled) { setCompareBars(null); setCompareError(String(e.message || e)); } });
    return () => { cancelled = true; };
  }, [comparePeer]);

  useEffect(() => {
    if (!containerRef.current || !candles?.bars?.length) return;
    const bars = candles.bars;
    const toDate = bars[bars.length - 1].date;
    const fromDate = rangeSel === 'All' ? bars[0].date : rangeStartDate(bars, rangeSel);
    const compareInRange = compareBars
      ? compareBars.filter((b) => b.date >= fromDate && b.date <= toDate)
      : [];

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: colors.muted },
      grid: { vertLines: { color: colors.gridline }, horzLines: { color: colors.gridline } },
      width: containerRef.current.clientWidth,
      height: 420,
      timeScale: { borderColor: colors.baseline },
      rightPriceScale: {
        borderColor: colors.baseline,
        mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
      },
      leftPriceScale: { visible: compareInRange.length > 0, borderColor: colors.baseline },
    });
    chartRef.current = chart;

    const priceSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.good, downColor: colors.critical,
      borderUpColor: colors.good, borderDownColor: colors.critical,
      wickUpColor: colors.good, wickDownColor: colors.critical,
    }, 0);
    priceSeries.setData(bars.map((b) => ({
      time: b.date, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    const maColors = [colors.blue, colors.violet];
    SMA_PERIODS.forEach((period, i) => {
      const maSeries = chart.addSeries(LineSeries, {
        color: maColors[i], lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      }, 0);
      maSeries.setData(sma(bars, period));
    });

    // Volume histogram in its own pane below the price pane, bars colored by
    // up/down day using the same tokens as the candle body/wick colors.
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: colors.good, priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false,
    }, 1);
    volumeSeries.setData(bars.map((b) => ({
      time: b.date, value: b.volume, color: b.close >= b.open ? colors.good : colors.critical,
    })));
    const panes = chart.panes();
    panes[0]?.setStretchFactor(3);
    panes[1]?.setStretchFactor(1);

    // Comparison line — peer/benchmark close normalised to 100 at the first
    // bar inside the currently selected range, on its own (left) price scale
    // so it reads as relative performance rather than fighting the $ axis.
    if (compareInRange.length > 0) {
      const base = compareInRange[0].close;
      const compareSeries = chart.addSeries(LineSeries, {
        color: colors.orange, lineWidth: 2, priceScaleId: 'left',
        priceLineVisible: false, lastValueVisible: true,
      }, 0);
      compareSeries.setData(compareInRange.map((b) => ({ time: b.date, value: (b.close / base) * 100 })));
    }

    if (rangeSel === 'All') {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().setVisibleRange({ from: fromDate, to: toDate });
    }

    const onCrosshairMove = (param: MouseEventParams) => {
      if (!param.time) { setCrosshair(null); return; }
      const bar = param.seriesData.get(priceSeries) as
        { open: number; high: number; low: number; close: number } | undefined;
      if (!bar) { setCrosshair(null); return; }
      const vol = param.seriesData.get(volumeSeries) as { value: number } | undefined;
      setCrosshair({
        date: String(param.time), open: bar.open, high: bar.high, low: bar.low, close: bar.close,
        volume: vol?.value ?? null,
      });
    };
    chart.subscribeCrosshairMove(onCrosshairMove);

    const onResize = () => chart.applyOptions({ width: containerRef.current?.clientWidth ?? 600 });
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chart.remove();
      chartRef.current = null;
      setCrosshair(null);
    };
  }, [candles, colors, themeTick, compareBars, rangeSel, logScale]);

  if (error) {
    return (
      <div className="panel">
        <h2>Price chart</h2>
        <p className="muted candle-empty">
          No real price data landed for this bank yet. Market data needs its own free
          Tiingo API key (unlike FDIC/SEC, which need no key at all) — see{' '}
          <code>scripts/land_market_data.ps1</code> in the repo. ({error})
        </p>
        {coverage?.landed_yet && (
          <p className="muted candle-coverage">
            {coverage.landed} of {coverage.eligible} eligible tickers landed so far
            ({coverage.coverage_pct}%) — coverage grows with each scheduled land run
            (Tiingo's free tier caps landing at 50 tickers/hour), this bank just isn't
            covered yet.
          </p>
        )}
      </div>
    );
  }

  const lastBar = candles?.bars?.length ? candles.bars[candles.bars.length - 1] : null;
  const readout: CrosshairInfo | null = crosshair ?? (lastBar && {
    date: lastBar.date, open: lastBar.open, high: lastBar.high, low: lastBar.low,
    close: lastBar.close, volume: lastBar.volume,
  });

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

      {candles && (
        <div className="candle-toolbar">
          <div className="candle-range-group" role="group" aria-label="Visible range">
            {(['1M', '3M', '6M', '1Y', 'All'] as const).map((r) => (
              <button
                key={r}
                type="button"
                className={`candle-range-btn${rangeSel === r ? ' active' : ''}`}
                onClick={() => setRangeSel(r)}
              >
                {r}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={`candle-scale-btn${logScale ? ' active' : ''}`}
            onClick={() => setLogScale((v) => !v)}
            title="Toggle logarithmic price scale"
          >
            Log
          </button>
          <div className="candle-compare">
            {comparePeer ? (
              <span className="candle-compare-chip">
                <i className="candle-compare-dot" /> vs {comparePeer.name}
                <button type="button" onClick={() => setComparePeer(null)} aria-label="Remove comparison">×</button>
              </span>
            ) : (
              <BankSearch onSelect={(pcert, name) => { if (pcert !== cert) setComparePeer({ cert: pcert, name }); }} />
            )}
          </div>
        </div>
      )}
      {compareError && <p className="muted candle-compare-error">Comparison unavailable: {compareError}</p>}

      <div className="candle-chart-wrap">
        <div ref={containerRef} className="candle-container" />
        {readout && (
          <div className="candle-crosshair-readout tabular">
            <span className="ccr-date">{readout.date}</span>
            <span>O <b>{readout.open.toFixed(2)}</b></span>
            <span>H <b>{readout.high.toFixed(2)}</b></span>
            <span>L <b>{readout.low.toFixed(2)}</b></span>
            <span className={readout.close >= readout.open ? 'candle-up' : 'candle-down'}>
              C <b>{readout.close.toFixed(2)}</b>
            </span>
            <span className="muted">Vol <b>{readout.volume !== null ? fmtVolume(readout.volume) : '—'}</b></span>
          </div>
        )}
      </div>
      <div className="candle-legend">
        <span className="candle-legend-item"><i style={{ background: colors.blue }} /> 50D SMA</span>
        <span className="candle-legend-item"><i style={{ background: colors.violet }} /> 200D SMA</span>
        {comparePeer && (
          <span className="candle-legend-item"><i style={{ background: colors.orange }} /> {comparePeer.name} (indexed to 100)</span>
        )}
      </div>

      <p className="muted chart-caption">
        Real EOD data (Tiingo) for {candles?.ticker} — the bank's crosswalk-matched
        ticker (exact/high-confidence match only).
        {coverage?.landed_yet && (
          <> Population coverage: {coverage.landed}/{coverage.eligible} eligible
            tickers ({coverage.coverage_pct}%){coverage.oldest_bar_age_days !== null
              && `, oldest bar ${coverage.oldest_bar_age_days}d old`}.</>
        )}
      </p>
    </div>
  );
}
