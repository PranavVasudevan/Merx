import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type BankSearchResult } from '../api';
import type {
  BulkStressResult, CustomScenarioItem, LiquiditySurvivalResult, NamedScenario, PopulationBank,
  RiskLeaderboardEntry, StressComparisonResult, StressProjectionResult, StressSurfaceResult, WatchlistItem,
} from '../types';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { RISK_DISCLAIMER, type CsvColumn } from '../csvExport';
import { CapitalWaterfallChart } from '../components/CapitalWaterfallChart';
import { MarginalContributionChart, type LegContribution } from '../components/MarginalContributionChart';
import { StressSurfaceChart } from '../components/StressSurfaceChart';
import '../components/StressPanel.css';
import './StressLabPage.css';

type Scope = 'top_assets' | 'cluster' | 'watchlist' | 'top_risk';
const MAX_BULK = 150;

function fmtB(v: number): string {
  return `$${(v / 1e9).toFixed(1)}B`;
}

export function StressLabPage() {
  const [loanLoss, setLoanLoss] = useState(3);
  const [outflow, setOutflow] = useState(15);
  const [rateBps, setRateBps] = useState(200);

  // D10 — named scenario registry (config/scenarios.json) + user-saved custom ones.
  const [namedScenarios, setNamedScenarios] = useState<NamedScenario[]>([]);
  const [customScenarios, setCustomScenarios] = useState<CustomScenarioItem[]>([]);
  const [activeScenarioNote, setActiveScenarioNote] = useState<string | null>(null);

  useEffect(() => {
    api.scenarioLibrary().then((r) => setNamedScenarios(r.scenarios)).catch(() => setNamedScenarios([]));
    api.getCustomScenarios().then((r) => setCustomScenarios(r.items)).catch(() => setCustomScenarios([]));
  }, []);

  function applyNamedScenario(id: string) {
    const s = namedScenarios.find((x) => x.id === id);
    if (!s) { setActiveScenarioNote(null); return; }
    setLoanLoss(s.loan_loss_pct); setOutflow(s.deposit_outflow_pct); setRateBps(s.rate_shock_bps);
    setActiveScenarioNote(`${s.description} — ${s.assumptions}`);
  }

  function applyCustomScenario(id: number) {
    const s = customScenarios.find((x) => x.id === id);
    if (!s) return;
    setLoanLoss(s.loan_loss_pct); setOutflow(s.deposit_outflow_pct); setRateBps(s.rate_shock_bps);
    setActiveScenarioNote(null);
  }

  async function saveCurrentAsScenario() {
    const name = window.prompt('Name this scenario:');
    if (!name) return;
    try {
      const r = await api.saveCustomScenario(name, loanLoss, outflow, rateBps);
      setCustomScenarios(r.items);
    } catch { /* non-critical, no banner needed for a save-scenario failure here */ }
  }

  async function deleteCustomScenario(id: number) {
    try {
      const r = await api.deleteCustomScenario(id);
      setCustomScenarios(r.items);
    } catch { /* non-critical */ }
  }

  const [scope, setScope] = useState<Scope>('top_assets');
  const [clusterLabel, setClusterLabel] = useState('');
  const [topN, setTopN] = useState(20);

  const [population, setPopulation] = useState<PopulationBank[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [riskTop, setRiskTop] = useState<RiskLeaderboardEntry[] | null>(null);

  const [bulk, setBulk] = useState<BulkStressResult | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  const [cmpCert, setCmpCert] = useState<number | null>(6976);
  const [cmpQuery, setCmpQuery] = useState('');
  const [cmpResults, setCmpResults] = useState<BankSearchResult['banks']>([]);
  const [cmp, setCmp] = useState<StressComparisonResult | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);

  const [horizon, setHorizon] = useState(4);
  const [projection, setProjection] = useState<StressProjectionResult | null>(null);
  const [projError, setProjError] = useState<string | null>(null);
  const [liquidity, setLiquidity] = useState<LiquiditySurvivalResult | null>(null);

  // E3(b) — marginal contribution per shock leg: base scenario vs three
  // "all-legs-minus-one" holdouts, all four re-run on the SAME bank/sliders so
  // they can't drift apart from independent effects.
  const [legContribs, setLegContribs] = useState<LegContribution[] | null>(null);
  const [legContribError, setLegContribError] = useState<string | null>(null);

  // E3(c) — CET1 surface over (deposit outflow x rate shock) for the same bank,
  // loan_loss_pct held at the slider value.
  const [surface, setSurface] = useState<StressSurfaceResult | null>(null);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);

  useEffect(() => {
    api.population().then((r) => setPopulation(r.banks));
    api.getWatchlist().then((r) => setWatchlist(r.items)).catch(() => setWatchlist([]));
  }, []);

  useEffect(() => {
    if (scope === 'top_risk' && riskTop === null) {
      api.riskLeaderboard(100).then((r) => setRiskTop(r.top)).catch(() => setRiskTop([]));
    }
  }, [scope, riskTop]);

  useEffect(() => {
    if (cmpQuery.trim().length < 2) { setCmpResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(cmpQuery, undefined, 8).then((r) => setCmpResults(r.banks)).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [cmpQuery]);

  const clusters = useMemo(
    () => [...new Set(population.map((b) => b.cluster_label))].filter((c): c is string => !!c),
    [population],
  );

  const resolvedCerts = useMemo(() => {
    if (scope === 'cluster') return population.filter((b) => b.cluster_label === clusterLabel).map((b) => b.cert);
    if (scope === 'watchlist') return watchlist.map((w) => w.cert);
    if (scope === 'top_risk') return (riskTop ?? []).map((r) => r.cert);
    return [...population].sort((a, b) => b.assets_b - a.assets_b).slice(0, topN).map((b) => b.cert);
  }, [scope, clusterLabel, topN, population, watchlist, riskTop]);

  useEffect(() => {
    const certs = resolvedCerts.slice(0, MAX_BULK);
    if (certs.length === 0) { setBulk(null); return; }
    setBulkLoading(true);
    const t = setTimeout(() => {
      api.bulkStressTest(certs, loanLoss, outflow, rateBps)
        .then((r) => { setBulk(r); setBulkError(null); })
        .catch((e: Error) => { setBulk(null); setBulkError(e.message); })
        .finally(() => setBulkLoading(false));
    }, 350);
    return () => clearTimeout(t);
  }, [resolvedCerts, loanLoss, outflow, rateBps]);

  useEffect(() => {
    if (cmpCert === null) return;
    const t = setTimeout(() => {
      api.stressComparison(cmpCert, loanLoss, outflow, rateBps)
        .then((r) => { setCmp(r); setCmpError(null); })
        .catch((e: Error) => { setCmp(null); setCmpError(e.message); });
    }, 350);
    return () => clearTimeout(t);
  }, [cmpCert, loanLoss, outflow, rateBps]);

  useEffect(() => {
    if (cmpCert === null) return;
    const t = setTimeout(() => {
      api.stressProjection(cmpCert, loanLoss, outflow, rateBps, horizon)
        .then((r) => { setProjection(r); setProjError(null); })
        .catch((e: Error) => { setProjection(null); setProjError(e.message); });
      api.liquiditySurvival(cmpCert, outflow).then(setLiquidity).catch(() => setLiquidity(null));
    }, 350);
    return () => clearTimeout(t);
  }, [cmpCert, loanLoss, outflow, rateBps, horizon]);

  // E3(b) — base scenario + three "all-legs-minus-one" holdouts (zero out one leg
  // at a time), all fetched together so they can never reflect different sliders.
  // Marginal contribution = base hit − holdout hit: how much of the capital hit
  // disappears when that leg is removed, including its share of interactions
  // (e.g. a rate shock only realizes an HTM loss if deposit outflow also forces
  // the sale — the holdout diff captures that, a naive per-leg isolation wouldn't).
  useEffect(() => {
    if (cmpCert === null) { setLegContribs(null); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      Promise.all([
        api.stressTest(cmpCert, loanLoss, outflow, rateBps),
        api.stressTest(cmpCert, 0, outflow, rateBps),
        api.stressTest(cmpCert, loanLoss, 0, rateBps),
        api.stressTest(cmpCert, loanLoss, outflow, 0),
      ]).then(([base, noLoanLoss, noOutflow, noRate]) => {
        if (cancelled) return;
        const baseHit = base.capital_waterfall.total_capital_hit;
        const notApplied = (leg: string) => base.legs_not_applied.some((l) => l.leg === leg);
        const diff = (variant: typeof base) => Math.max(0, baseHit - variant.capital_waterfall.total_capital_hit);
        setLegContribs([
          { leg: 'loan_loss', label: 'Loan losses', contribution: diff(noLoanLoss), applicable: !notApplied('loan_loss') },
          { leg: 'deposit_outflow', label: 'Deposit outflow (incl. forced HTM sale)', contribution: diff(noOutflow), applicable: !notApplied('deposit_outflow') },
          { leg: 'rate_shock', label: 'Rate shock (AFS mark + HTM if realized)', contribution: diff(noRate), applicable: !notApplied('rate_shock') },
        ]);
        setLegContribError(null);
      }).catch((e: Error) => { if (!cancelled) { setLegContribs(null); setLegContribError(e.message); } });
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [cmpCert, loanLoss, outflow, rateBps]);

  // E3(c) — the surface only varies deposit outflow x rate shock; loan_loss_pct
  // is held fixed at the slider value (an independent third axis would need a
  // 3-D surface, out of scope here — the caption on the chart says so).
  useEffect(() => {
    if (cmpCert === null) { setSurface(null); return; }
    const t = setTimeout(() => {
      api.stressSurface(cmpCert, loanLoss, 90, 500, 7)
        .then((r) => { setSurface(r); setSurfaceError(null); })
        .catch((e: Error) => { setSurface(null); setSurfaceError(e.message); });
    }, 400);
    return () => clearTimeout(t);
  }, [cmpCert, loanLoss]);

  return (
    <div className="stress-lab-page">
      <div className="panel">
        <h2>Stress lab</h2>
        <p className="muted stress-lab-subtitle">
          Feature 16, cross-bank — the same scenario applied to a whole cluster,
          your watchlist, or a top-N slice at once, plus a real QuantLib DCF
          re-price compared against the linear-duration approximation for one bank.
        </p>
        <p className="muted chart-caption">
          Pass/fail verdicts below are this scenario applied to disclosed regulatory minimums —
          not a supervisory stress test and not a prediction of which banks will actually fail.
          {' '}{RISK_DISCLAIMER}
        </p>
        <div className="stress-scenario-picker">
          <select
            className="stress-lab-select"
            defaultValue=""
            onChange={(e) => { if (e.target.value) applyNamedScenario(e.target.value); e.target.value = ''; }}
          >
            <option value="" disabled>Load a named scenario…</option>
            {namedScenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {customScenarios.length > 0 && (
            <select
              className="stress-lab-select"
              defaultValue=""
              onChange={(e) => { if (e.target.value) applyCustomScenario(Number(e.target.value)); e.target.value = ''; }}
            >
              <option value="" disabled>Load a saved scenario…</option>
              {customScenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )}
          <button className="stress-scenario-save" onClick={saveCurrentAsScenario}>Save current as scenario</button>
          {customScenarios.map((s) => (
            <button
              key={`del-${s.id}`}
              className="stress-scenario-delete"
              onClick={() => deleteCustomScenario(s.id)}
              title={`Delete saved scenario "${s.name}"`}
            >
              🗑 {s.name}
            </button>
          ))}
        </div>
        {activeScenarioNote && <p className="muted chart-caption stress-scenario-note">{activeScenarioNote}</p>}
        <div className="stress-controls">
          <label className="stress-slider">
            <span>Loan losses <b className="tabular">{loanLoss.toFixed(0)}%</b></span>
            <input type="range" min={0} max={15} step={1} value={loanLoss}
              onChange={(e) => setLoanLoss(Number(e.target.value))} />
          </label>
          <label className="stress-slider">
            <span>Deposit outflow <b className="tabular">{outflow.toFixed(0)}%</b></span>
            <input type="range" min={0} max={90} step={5} value={outflow}
              onChange={(e) => setOutflow(Number(e.target.value))} />
          </label>
          <label className="stress-slider">
            <span>Rate shock <b className="tabular">+{rateBps.toFixed(0)}bps</b></span>
            <input type="range" min={0} max={500} step={25} value={rateBps}
              onChange={(e) => setRateBps(Number(e.target.value))} />
          </label>
        </div>
      </div>

      <div className="panel">
        <h2>Cross-bank scenario</h2>
        <div className="stress-lab-scope">
          <select className="stress-lab-select" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="top_assets">Top N by assets</option>
            <option value="cluster">Behavioral cluster</option>
            <option value="watchlist">My watchlist</option>
            <option value="top_risk">Top N riskiest (deposit-flight model)</option>
          </select>
          {(scope === 'top_assets' || scope === 'top_risk') && (
            <select className="stress-lab-select" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
              {[10, 20, 50, 100].map((n) => <option key={n} value={n}>N = {n}</option>)}
            </select>
          )}
          {scope === 'cluster' && (
            <select className="stress-lab-select" value={clusterLabel} onChange={(e) => setClusterLabel(e.target.value)}>
              <option value="">Choose a cluster…</option>
              {clusters.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
        </div>
        {resolvedCerts.length > MAX_BULK && (
          <p className="muted stress-lab-truncation">
            Showing the first {MAX_BULK} of {resolvedCerts.length} banks in this scope.
          </p>
        )}
        {scope === 'watchlist' && watchlist.length === 0 && (
          <p className="muted">Your watchlist is empty — add banks from any bank page.</p>
        )}
        {bulkError && <p className="app-banner-error">{bulkError}</p>}

        {bulk && (
          <>
            <div className="stress-lab-stats">
              <div className="stress-lab-stat"><span className="muted">Tested</span><span className="tabular">{bulk.tested}</span></div>
              <div className="stress-lab-stat"><span className="muted">Fail regulatory minimum</span><span className="tabular stress-bad-text">{bulk.fail_count}</span></div>
              <div className="stress-lab-stat"><span className="muted">Skipped</span><span className="tabular">{bulk.skipped.length}</span></div>
              {bulkLoading && <span className="muted"> recalculating…</span>}
              <ExportCsvButton
                filename="banklens-stress-lab.csv"
                columns={[
                  { key: 'name', label: 'Bank', value: (r) => r.name, source: 'fdic' },
                  { key: 'cert', label: 'FDIC Cert', value: (r) => r.cert, source: 'fdic' },
                  { key: 'cet1_before', label: 'CET1 before %', value: (r) => r.before.cet1 ?? 'n/a', source: 'derived' },
                  { key: 'cet1_after', label: 'CET1 after %', value: (r) => r.after.cet1 ?? 'n/a', source: 'derived' },
                  { key: 'passes_all', label: 'Passes all minimums',
                    value: (r) => (r.passes_all === null ? 'n/a' : r.passes_all ? 'yes' : 'no'), source: 'derived' },
                ] as CsvColumn<BulkStressResult['results'][number]>[]}
                rows={bulk.results}
                meta={{ sourceLabel: `Scenario: ${loanLoss}% loan loss / ${outflow}% outflow / +${rateBps}bps rate shock` }}
              />
            </div>
            <div className="stress-lab-results">
              {bulk.results.map((r) => (
                <Link className="stress-lab-row" key={r.cert} to={`/bank/${r.cert}`}>
                  <span className={
                    r.passes_all === null ? 'stress-lab-dot' : r.passes_all ? 'stress-lab-dot stress-lab-dot-pass' : 'stress-lab-dot stress-lab-dot-fail'
                  } />
                  <span className="stress-lab-name">{r.name}</span>
                  <span className="tabular muted">{r.before.cet1 === null ? 'n/a' : `${r.before.cet1}%`}</span>
                  <span className="muted">→</span>
                  <span className={`tabular ${r.passes.cet1 === undefined ? '' : r.passes.cet1 ? 'stress-good-text' : 'stress-bad-text'}`}>
                    {r.after.cet1 === null ? 'n/a' : `${r.after.cet1}%`}
                  </span>
                </Link>
              ))}
            </div>
            {bulk.skipped.length > 0 && (
              <p className="muted stress-lab-skipped">
                Skipped: {bulk.skipped.map((s) => `${s.name ?? `CERT ${s.cert}`} (${s.reason})`).join('; ')}
              </p>
            )}
          </>
        )}
      </div>

      <div className="panel">
        <h2>Pricing-engine comparison</h2>
        <p className="muted chart-caption stress-lab-cmp-caption">
          The same rate shock, priced two ways for one bank: the linear-duration
          approximation vs a real QuantLib DCF re-price. The DCF version captures
          bond convexity, so it should consistently show a SMALLER loss for the
          same shock.
        </p>
        <p className="muted chart-caption stress-lab-cmp-caption">
          <strong>What the QuantLib model actually is (C7):</strong> an FDIC call report
          discloses one AFS dollar total and one HTM dollar total per bank, not
          holdings-level detail — so both engines assume a single "average duration" per
          book, and the QuantLib path prices ONE representative bullet bond with that many
          years to maturity, not a real ladder of the bank's actual holdings. It is a real
          discounted-cash-flow re-price (captures convexity a linear formula can't), but it
          is still a single-bond proxy for a book that in reality holds many instruments —
          not a claim of holdings-level accuracy. Duration itself is a fallback assumption
          (4y AFS / 6y HTM) unless a future maturity-bucket connector lands real per-bank
          figures — see each result's <code>duration_sources</code>.
        </p>
        <input
          className="stress-lab-cmp-input"
          placeholder="Search a bank…"
          value={cmpQuery}
          onChange={(e) => setCmpQuery(e.target.value)}
        />
        {cmpResults.length > 0 && (
          <div className="stress-lab-cmp-results">
            {cmpResults.map((b) => (
              <button key={b.cert} className="stress-lab-cmp-result"
                onClick={() => { setCmpCert(b.cert); setCmpQuery(''); setCmpResults([]); }}>
                {b.name}
              </button>
            ))}
          </div>
        )}
        {cmpError && <p className="app-banner-error">{cmpError}</p>}
        {cmp && (
          <>
            <h3 className="stress-lab-cmp-name">{cmp.name}</h3>
            <div className="stress-lab-cmp-grid">
              <div className="stress-lab-cmp-col">
                <div className="stress-lab-cmp-label">Linear duration</div>
                <div className="stress-lab-cmp-loss tabular">{fmtB(cmp.linear.capital_waterfall.afs_mark_loss + cmp.linear.capital_waterfall.htm_realized_loss)}</div>
                <div className="muted tabular">CET1 after: {cmp.linear.after.cet1}%</div>
                {cmp.linear.duration_sources && (
                  <div className="muted tabular stress-lab-cmp-duration">
                    {cmp.linear.duration_sources.afs_duration_used}y AFS / {cmp.linear.duration_sources.htm_duration_used}y HTM
                    {' '}({cmp.linear.duration_sources.afs === 'fallback_default' ? 'assumed default' : cmp.linear.duration_sources.afs})
                  </div>
                )}
              </div>
              <div className="stress-lab-cmp-col">
                <div className="stress-lab-cmp-label">QuantLib DCF re-price (single representative bond)</div>
                <div className="stress-lab-cmp-loss tabular">{fmtB(cmp.quantlib.capital_waterfall.afs_mark_loss + cmp.quantlib.capital_waterfall.htm_realized_loss)}</div>
                <div className="muted tabular">CET1 after: {cmp.quantlib.after.cet1}%</div>
              </div>
            </div>
            <p className="muted stress-lab-cmp-delta">
              Convexity effect: QuantLib reports{' '}
              {fmtB(Math.abs((cmp.linear.capital_waterfall.afs_mark_loss + cmp.linear.capital_waterfall.htm_realized_loss)
                - (cmp.quantlib.capital_waterfall.afs_mark_loss + cmp.quantlib.capital_waterfall.htm_realized_loss)))}{' '}
              {(cmp.linear.capital_waterfall.afs_mark_loss + cmp.linear.capital_waterfall.htm_realized_loss)
                >= (cmp.quantlib.capital_waterfall.afs_mark_loss + cmp.quantlib.capital_waterfall.htm_realized_loss)
                ? 'less' : 'more'} securities loss than the linear approximation for the same shock.
            </p>
          </>
        )}
      </div>

      <div className="panel">
        <h2>Capital-bridge waterfall</h2>
        <p className="muted chart-caption stress-lab-cmp-caption">
          The same bank picked above — starting CET1 capital down to stressed CET1
          capital, decomposed into the real dollar loss legs (linear-duration pricing).
        </p>
        {!cmpCert && <p className="muted">Search a bank above to see its capital bridge.</p>}
        {cmp && <CapitalWaterfallChart result={cmp.linear} />}
      </div>

      <div className="panel">
        <h2>Marginal contribution by shock leg</h2>
        <p className="muted chart-caption stress-lab-cmp-caption">
          How much of the total capital hit disappears when one leg is held out (all
          legs minus one), re-run for real on this bank — captures interaction effects
          like the SVB chain, not just each leg priced in isolation.
        </p>
        {!cmpCert && <p className="muted">Search a bank above to rank its shock legs.</p>}
        {legContribError && <p className="app-banner-error">{legContribError}</p>}
        {legContribs && <MarginalContributionChart contributions={legContribs} />}
      </div>

      <div className="panel">
        <h2>CET1 surface: deposit outflow x rate shock</h2>
        <p className="muted chart-caption stress-lab-cmp-caption">
          The same bank's stressed CET1 across a 7x7 grid of deposit outflow and rate
          shock combinations, computed server-side in one request — the color boundary
          at the regulatory minimum is the real pass/fail contour, not an interpolation.
        </p>
        {!cmpCert && <p className="muted">Search a bank above to render its stress surface.</p>}
        {surfaceError && <p className="app-banner-error">{surfaceError}</p>}
        {surface && <StressSurfaceChart result={surface} />}
      </div>

      <div className="panel">
        <h2>Multi-period projection</h2>
        <p className="muted chart-caption stress-lab-cmp-caption">
          The same bank as the pricing-engine comparison above — search there to pick one.
          The shock phases in linearly over the horizon; disclosed pre-provision net revenue
          (PPNR) earns back part of each period's loss instead of every shock reading as one
          instantaneous, un-offset hit.
        </p>
        <div className="stress-lab-scope">
          <select className="stress-lab-select" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {[4, 6, 8].map((n) => <option key={n} value={n}>{n} quarters</option>)}
          </select>
        </div>
        {projError && <p className="app-banner-error">{projError}</p>}
        {!cmpCert && <p className="muted">Search a bank above to run a projection.</p>}
        {projection && (
          <>
            <div className="stress-lab-stats">
              <div className="stress-lab-stat">
                <span className="muted">PPNR / quarter (estimated)</span>
                <span className="tabular">
                  {projection.ppnr_quarterly_estimated === null ? 'n/a — undisclosed'
                    : fmtB(projection.ppnr_quarterly_estimated)}
                </span>
              </div>
              <div className="stress-lab-stat">
                <span className="muted">Breaches a minimum at</span>
                <span className={`tabular ${projection.breach_quarter ? 'stress-bad-text' : 'stress-good-text'}`}>
                  {projection.breach_quarter ? `Q${projection.breach_quarter}` : `survives all ${projection.horizon_quarters}Q`}
                </span>
              </div>
              {liquidity?.applicable && (
                <div className="stress-lab-stat">
                  <span className="muted">Liquidity survival at {outflow.toFixed(0)}%/qtr sustained</span>
                  <span className={`tabular ${liquidity.breach_quarter ? 'stress-bad-text' : 'stress-good-text'}`}>
                    {liquidity.breach_quarter ? `${liquidity.quarters_survived}Q then exhausted` : `${liquidity.quarters_survived}Q+ (checked)`}
                  </span>
                </div>
              )}
            </div>
            <div className="stress-lab-results">
              {projection.path.map((p) => (
                <div className="stress-lab-row" key={p.quarter_offset}>
                  <span className={
                    p.passes_all === null ? 'stress-lab-dot' : p.passes_all ? 'stress-lab-dot stress-lab-dot-pass' : 'stress-lab-dot stress-lab-dot-fail'
                  } />
                  <span className="stress-lab-name">Q{p.quarter_offset}</span>
                  <span className="tabular muted">hit {fmtB(p.gross_capital_hit)}</span>
                  <span className="muted">− PPNR {fmtB(p.ppnr_offset_applied)} =</span>
                  <span className={`tabular ${p.passes.cet1 === undefined ? '' : p.passes.cet1 ? 'stress-good-text' : 'stress-bad-text'}`}>
                    CET1 {p.after.cet1 === null ? 'n/a' : `${p.after.cet1}%`}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
