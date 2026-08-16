import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { RISK_DISCLAIMER } from '../csvExport';
import type { PortfolioPosition, PortfolioSummaryResult } from '../types';
import './PortfolioPage.css';

function fmtUsd(v: number): string {
  return v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : `$${v.toLocaleString()}`;
}

const SEV_LABEL: Record<string, string> = { low: 'Low', elevated: 'Elevated', high: 'High' };

/** D11 — a counterparty-exposure portfolio: (bank, exposure amount, exposure
 * type) positions persisted per user, with an exposure-weighted aggregate
 * view (X-Ray severity, risk resemblance, concentration, stress pass/fail). */
export function PortfolioPage() {
  const [positions, setPositions] = useState<PortfolioPosition[] | null>(null);
  const [summary, setSummary] = useState<PortfolioSummaryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [certInput, setCertInput] = useState('');
  const [amountInput, setAmountInput] = useState('');
  const [typeInput, setTypeInput] = useState('loan');
  const [busy, setBusy] = useState(false);

  function load() {
    api.getPortfolio().then((r) => setPositions(r.items)).catch(() => setPositions([]));
    api.portfolioSummary().then(setSummary).catch(() => setSummary(null));
  }

  useEffect(() => { load(); }, []);

  async function addPosition() {
    const cert = Number(certInput);
    const amount = Number(amountInput);
    if (!cert || !amount || !typeInput.trim()) return;
    setBusy(true);
    try {
      await api.addPortfolioPosition(cert, amount, typeInput.trim());
      setCertInput(''); setAmountInput('');
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function removePosition(id: number) {
    try {
      await api.deletePortfolioPosition(id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const concByState = Object.entries(summary?.concentration_by_state ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const concByCluster = Object.entries(summary?.concentration_by_cluster ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8);

  return (
    <div className="portfolio-page">
      <div className="panel">
        <h2>Portfolio</h2>
        <p className="muted portfolio-subtitle">
          Counterparty exposure positions — enter a bank's FDIC CERT, an exposure amount and type
          (loan, bond, deposit relationship, etc.). {RISK_DISCLAIMER}
        </p>
        <div className="portfolio-add-row">
          <input className="portfolio-input" placeholder="FDIC CERT" value={certInput}
            onChange={(e) => setCertInput(e.target.value)} />
          <input className="portfolio-input" placeholder="Exposure amount ($)" type="number" value={amountInput}
            onChange={(e) => setAmountInput(e.target.value)} />
          <input className="portfolio-input" placeholder="Exposure type" value={typeInput}
            onChange={(e) => setTypeInput(e.target.value)} />
          <button className="portfolio-add-btn" onClick={addPosition} disabled={busy}>+ Add position</button>
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {summary && summary.positions > 0 && (
        <div className="panel">
          <h2>Aggregate view — {summary.positions} position{summary.positions === 1 ? '' : 's'}, {fmtUsd(summary.total_exposure)} total</h2>
          <div className="portfolio-stats">
            <div className="portfolio-stat">
              <span className="muted">Exposure-weighted X-Ray severity</span>
              <span className={`portfolio-stat-value chip chip-${summary.exposure_weighted_xray_severity ?? 'low'}`}>
                {summary.exposure_weighted_xray_severity ? SEV_LABEL[summary.exposure_weighted_xray_severity] : '—'}
              </span>
            </div>
            <div className="portfolio-stat">
              <span className="muted">Exposure-weighted risk resemblance</span>
              <span className="portfolio-stat-value tabular">
                {summary.exposure_weighted_risk_resemblance_percentile != null
                  ? `${summary.exposure_weighted_risk_resemblance_percentile.toFixed(0)}th pctile` : '—'}
              </span>
            </div>
            {summary.stress_summary && (
              <>
                <div className="portfolio-stat">
                  <span className="muted">Exposure passing stress minimums</span>
                  <span className="portfolio-stat-value tabular stress-good-text">{fmtUsd(summary.stress_summary.exposure_passing)}</span>
                </div>
                <div className="portfolio-stat">
                  <span className="muted">Exposure failing stress minimums</span>
                  <span className="portfolio-stat-value tabular stress-bad-text">{fmtUsd(summary.stress_summary.exposure_failing)}</span>
                </div>
              </>
            )}
          </div>
          <p className="muted portfolio-stress-caption">
            Stress: 3% loan loss / 15% deposit outflow / +200bps rate shock (see /stress-lab for the same engine) —
            weighted by how much of your exposure sits with each bank, not a loss-given-default on the exposure itself.
          </p>

          <div className="portfolio-conc-grid">
            <div>
              <h3 className="portfolio-conc-title">Concentration by state</h3>
              {concByState.map(([k, v]) => (
                <div className="portfolio-conc-row" key={k}>
                  <span>{k}</span><span className="tabular">{fmtUsd(v)}</span>
                </div>
              ))}
            </div>
            <div>
              <h3 className="portfolio-conc-title">Concentration by behavioral cluster</h3>
              {concByCluster.map(([k, v]) => (
                <div className="portfolio-conc-row" key={k}>
                  <span>{k}</span><span className="tabular">{fmtUsd(v)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {positions && positions.length > 0 && (
        <div className="panel">
          <h2>Positions</h2>
          <table className="portfolio-table">
            <thead>
              <tr><th>Bank</th><th>Exposure</th><th>Type</th><th></th></tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/bank/${p.cert}`}>CERT {p.cert}</Link></td>
                  <td className="tabular">{fmtUsd(p.exposure_amount)}</td>
                  <td>{p.exposure_type}</td>
                  <td>
                    <button className="portfolio-remove-btn" onClick={() => removePosition(p.id)} aria-label="Remove position">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {positions && positions.length === 0 && (
        <div className="panel">
          <p className="muted">No positions yet — add one above to see the aggregate view.</p>
        </div>
      )}
    </div>
  );
}
