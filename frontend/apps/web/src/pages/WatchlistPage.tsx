import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { api } from '../api';
import { chartColors } from '../colors';
import type { PopulationBank, RiskScoreResult, XrayResult } from '../types';
import './WatchlistPage.css';

const SEV_LABEL: Record<string, string> = { low: 'Low', elevated: 'Elevated', high: 'High' };

interface WatchedBank {
  cert: number;
  created_at: string;
  info: PopulationBank | null;
  riskScore: RiskScoreResult | null;
  xray: XrayResult | null;
}

// Same 0.5/0.15 thresholds RiskScorePanel.tsx and OverviewPage.tsx use.
function riskZoneColor(score: number, colors: ReturnType<typeof chartColors>): string {
  if (score >= 0.5) return colors.critical;
  if (score >= 0.15) return colors.warning;
  return colors.good;
}

export function WatchlistPage() {
  const [rows, setRows] = useState<WatchedBank[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const colors = chartColors();

  useEffect(() => { load(); }, []);

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
      })
      .catch((e) => setError(String(e.message || e)));
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

  return (
    <div className="watchlist-page">
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
                      <span className="tabular watchlist-row-risk-value" style={{ color: riskZoneColor(row.riskScore.risk_score, colors) }}>
                        {(row.riskScore.risk_score * 100).toFixed(1)}%
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
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
