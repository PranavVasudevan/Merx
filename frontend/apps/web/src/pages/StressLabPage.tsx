import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type BankSearchResult } from '../api';
import type {
  BulkStressResult, PopulationBank, RiskLeaderboardEntry, StressComparisonResult, WatchlistItem,
} from '../types';
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

  return (
    <div className="stress-lab-page">
      <div className="panel">
        <h2>Stress lab</h2>
        <p className="muted stress-lab-subtitle">
          Feature 16, cross-bank — the same scenario applied to a whole cluster,
          your watchlist, or a top-N slice at once, plus a real QuantLib DCF
          re-price compared against the linear-duration approximation for one bank.
        </p>
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
            </div>
            <div className="stress-lab-results">
              {bulk.results.map((r) => (
                <Link className="stress-lab-row" key={r.cert} to={`/bank/${r.cert}`}>
                  <span className={r.passes_all ? 'stress-lab-dot stress-lab-dot-pass' : 'stress-lab-dot stress-lab-dot-fail'} />
                  <span className="stress-lab-name">{r.name}</span>
                  <span className="tabular muted">{r.before.cet1}%</span>
                  <span className="muted">→</span>
                  <span className={`tabular ${r.passes.cet1 ? 'stress-good-text' : 'stress-bad-text'}`}>{r.after.cet1}%</span>
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
              </div>
              <div className="stress-lab-cmp-col">
                <div className="stress-lab-cmp-label">QuantLib DCF re-price</div>
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
    </div>
  );
}
