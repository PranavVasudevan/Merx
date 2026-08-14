import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import { resemblanceZone } from '../colors';
import type {
  AlertItem, PopulationBank, RiskScoreResult, WatchlistRule, WatchlistRuleType, XrayResult,
} from '../types';
import './WatchlistPage.css';

const SEV_LABEL: Record<string, string> = { low: 'Low', elevated: 'Elevated', high: 'High' };

const RULE_METRICS: { value: string; label: string }[] = [
  { value: 'uninsured_deposit_pct', label: 'Uninsured deposits' },
  { value: 'cet1_ratio', label: 'CET1 ratio' },
  { value: 'npl_ratio_pct', label: 'NPL ratio' },
  { value: 'loan_to_deposit_pct', label: 'Loan / deposit ratio' },
  { value: 'texas_ratio_pct', label: 'Texas Ratio' },
];

function ruleLabel(r: WatchlistRule): string {
  const metricLabel = RULE_METRICS.find((m) => m.value === r.metric)?.label ?? r.metric;
  if (r.rule_type === 'metric_threshold') {
    return `${metricLabel} ${r.operator === 'gt' ? '>' : '<'} ${r.threshold}`;
  }
  if (r.rule_type === 'metric_delta') {
    return `${metricLabel} moves more than ${r.threshold}pp`;
  }
  if (r.rule_type === 'xray_severity_increase') {
    return 'X-Ray severity increases';
  }
  return `enters the top ${r.top_n ?? 25} risk leaderboard`;
}

interface WatchedBank {
  cert: number;
  created_at: string;
  note: string | null;
  info: PopulationBank | null;
  riskScore: RiskScoreResult | null;
  xray: XrayResult | null;
}

export function WatchlistPage() {
  const [rows, setRows] = useState<WatchedBank[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<number, string>>({});
  const [rules, setRules] = useState<WatchlistRule[]>([]);
  const [ruleFormCert, setRuleFormCert] = useState<number | null>(null);
  const [ruleType, setRuleType] = useState<WatchlistRuleType>('metric_threshold');
  const [ruleMetric, setRuleMetric] = useState('uninsured_deposit_pct');
  const [ruleOperator, setRuleOperator] = useState<'gt' | 'lt'>('gt');
  const [ruleThreshold, setRuleThreshold] = useState('3');
  const [ruleTopN, setRuleTopN] = useState('25');
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  useEffect(() => { load(); loadRulesAndAlerts(); }, []);

  function load() {
    setRows(null);
    setError(null);
    Promise.all([api.getWatchlist(), api.population()])
      .then(async ([wl, pop]) => {
        const byCert = new Map(pop.banks.map((b) => [b.cert, b]));
        // Watchlists are personal and small — a handful of parallel per-bank
        // calls (same pattern BankPage already uses for one bank) is fine;
        // no new "hydrate these certs" backend endpoint needed for this.
        const hydrated = await Promise.all(wl.items.map(async (item) => {
          const [riskScore, xray] = await Promise.all([
            api.riskScore(item.cert).catch(() => null),
            api.xray(item.cert).catch(() => null),
          ]);
          return { ...item, info: byCert.get(item.cert) ?? null, riskScore, xray };
        }));
        setRows(hydrated);
        setNoteDrafts(Object.fromEntries(hydrated.map((r) => [r.cert, r.note ?? ''])));
      })
      .catch((e) => setError(String(e.message || e)));
  }

  function loadRulesAndAlerts() {
    api.getWatchlistRules().then((r) => setRules(r.items)).catch(() => setRules([]));
    api.getAlerts({ limit: 30 }).then((r) => setAlerts(r.items)).catch(() => setAlerts([]));
  }

  async function remove(cert: number) {
    setRemoving(cert);
    try {
      await api.removeFromWatchlist(cert);
      setRows((r) => r?.filter((row) => row.cert !== cert) ?? r);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setRemoving(null);
    }
  }

  async function saveNote(cert: number) {
    try {
      await api.setWatchlistNote(cert, noteDrafts[cert] ?? '');
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }

  async function addRule(cert: number) {
    try {
      const opts: Parameters<typeof api.addWatchlistRule>[2] = ruleType === 'risk_leaderboard_entry'
        ? { top_n: Number(ruleTopN) }
        : ruleType === 'xray_severity_increase'
          ? {}
          : { metric: ruleMetric, operator: ruleOperator, threshold: Number(ruleThreshold) };
      const r = await api.addWatchlistRule(cert, ruleType, opts);
      setRules(r.items);
      setRuleFormCert(null);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }

  async function removeRule(ruleId: number) {
    try {
      const r = await api.removeWatchlistRule(ruleId);
      setRules(r.items);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }

  async function markSeen(alertId: number) {
    try {
      const r = await api.markAlertSeen(alertId);
      setAlerts(r.items);
    } catch {
      // non-critical — leave the alert as unseen rather than surface a banner error
    }
  }

  const unseenAlerts = alerts.filter((a) => !a.seen);

  return (
    <div className="watchlist-page">
      {alerts.length > 0 && (
        <div className="panel">
          <h2>Alerts{unseenAlerts.length > 0 ? ` — ${unseenAlerts.length} new` : ''}</h2>
          <p className="muted watchlist-note">
            Triggered by the threshold rules below, evaluated after each quarterly data refresh.
            No email delivery yet — in-app only.
          </p>
          <div className="watchlist-alerts">
            {alerts.map((a) => (
              <div key={a.id} className={`watchlist-alert${a.seen ? '' : ' watchlist-alert-unseen'}`}>
                <Link to={`/bank/${a.cert}`} className="watchlist-alert-bank">
                  {rows?.find((r) => r.cert === a.cert)?.info?.name ?? `CERT ${a.cert}`}
                </Link>
                <span className="watchlist-alert-message">{a.message}</span>
                {!a.seen && (
                  <button className="watchlist-alert-dismiss" onClick={() => markSeen(a.id)}>
                    Mark seen
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Watchlist</h2>
        <p className="muted watchlist-note">
          Banks you're tracking — live risk scores and X-ray flags, not a bare list of certs.
        </p>

        {error && <p className="app-banner-error">{error}</p>}

        {rows && rows.length === 0 && (
          <p className="muted watchlist-empty">
            Nothing here yet — add a bank from its dashboard or the Screener.
          </p>
        )}

        {rows && rows.length > 0 && (
          <div className="watchlist-list">
            {rows.map((row, i) => (
              <motion.div
                key={row.cert}
                className="watchlist-row"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i, 12) * 0.03 } }}
              >
                <div className="watchlist-row-main">
                  <Link className="watchlist-row-name" to={`/bank/${row.cert}`}>
                    {row.info?.name ?? `CERT ${row.cert}`}
                  </Link>
                  <span className="muted watchlist-row-meta">
                    {row.info ? `$${row.info.assets_b.toFixed(1)}B · ${row.info.state ?? '—'}` : `CERT ${row.cert}`}
                  </span>
                </div>

                <div className="watchlist-row-risk">
                  {row.riskScore ? (
                    <>
                      <span className="tabular watchlist-row-risk-value" style={{ color: resemblanceZone(row.riskScore.resemblance_percentile).color }}>
                        {row.riskScore.resemblance_percentile === null ? '—' : `${row.riskScore.resemblance_percentile.toFixed(0)}th pctile`}
                      </span>
                      <span className="muted watchlist-row-risk-label">deposit-flight</span>
                    </>
                  ) : (
                    <span className="muted watchlist-row-risk-label">risk score unavailable</span>
                  )}
                </div>

                <div className="watchlist-row-flags">
                  {row.xray ? (
                    row.xray.flag_count > 0 ? (
                      <span className={`chip chip-${row.xray.overall_risk}`}>
                        {SEV_LABEL[row.xray.overall_risk]} · {row.xray.flag_count} flag{row.xray.flag_count === 1 ? '' : 's'}
                      </span>
                    ) : (
                      <span className="muted">no X-ray flags</span>
                    )
                  ) : (
                    <span className="muted">—</span>
                  )}
                </div>

                <button
                  className="watchlist-row-remove"
                  onClick={() => remove(row.cert)}
                  disabled={removing === row.cert}
                  aria-label={`Remove ${row.info?.name ?? row.cert} from watchlist`}
                >
                  ×
                </button>

                <div className="watchlist-row-detail">
                  <textarea
                    className="watchlist-row-note-input"
                    placeholder="Notes…"
                    rows={2}
                    value={noteDrafts[row.cert] ?? ''}
                    onChange={(e) => setNoteDrafts((d) => ({ ...d, [row.cert]: e.target.value }))}
                    onBlur={() => saveNote(row.cert)}
                  />
                  <div className="watchlist-row-rules">
                    {rules.filter((r) => r.cert === row.cert).map((r) => (
                      <span key={r.id} className="watchlist-rule-chip">
                        {ruleLabel(r)}
                        <button onClick={() => removeRule(r.id)} aria-label="Remove rule">×</button>
                      </span>
                    ))}
                    {ruleFormCert === row.cert ? (
                      <div className="watchlist-rule-form">
                        <select value={ruleType} onChange={(e) => setRuleType(e.target.value as WatchlistRuleType)}>
                          <option value="metric_threshold">Metric crosses threshold</option>
                          <option value="metric_delta">Metric moves more than…</option>
                          <option value="xray_severity_increase">X-Ray severity increases</option>
                          <option value="risk_leaderboard_entry">Enters top-N risk leaderboard</option>
                        </select>
                        {(ruleType === 'metric_threshold' || ruleType === 'metric_delta') && (
                          <>
                            <select value={ruleMetric} onChange={(e) => setRuleMetric(e.target.value)}>
                              {RULE_METRICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                            </select>
                            {ruleType === 'metric_threshold' && (
                              <select value={ruleOperator} onChange={(e) => setRuleOperator(e.target.value as 'gt' | 'lt')}>
                                <option value="gt">above</option>
                                <option value="lt">below</option>
                              </select>
                            )}
                            <input
                              type="number" className="watchlist-rule-num"
                              value={ruleThreshold} onChange={(e) => setRuleThreshold(e.target.value)}
                            />
                          </>
                        )}
                        {ruleType === 'risk_leaderboard_entry' && (
                          <input
                            type="number" className="watchlist-rule-num"
                            value={ruleTopN} onChange={(e) => setRuleTopN(e.target.value)}
                          />
                        )}
                        <button onClick={() => addRule(row.cert)}>Save</button>
                        <button onClick={() => setRuleFormCert(null)}>Cancel</button>
                      </div>
                    ) : (
                      <button className="watchlist-rule-add" onClick={() => setRuleFormCert(row.cert)}>
                        + alert rule
                      </button>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
