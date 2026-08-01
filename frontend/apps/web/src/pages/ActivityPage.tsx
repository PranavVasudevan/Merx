import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AgentRunEntry, AuditLogEntry } from '../types';
import './ActivityPage.css';

function fmtTs(ts: string): string {
  return new Date(ts).toLocaleString();
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

export function ActivityPage() {
  const [runs, setRuns] = useState<AgentRunEntry[] | null>(null);
  const [audit, setAudit] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.agentRuns(50), api.auditLog(100)])
      .then(([r, a]) => { setRuns(r.items); setAudit(a.items); })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  return (
    <div className="activity-page">
      <div className="panel">
        <h2>Agent-fleet activity</h2>
        <p className="muted activity-note">
          This is <strong>not</strong> a general audit trail of everything happening in BankLens —
          browsing the dashboard doesn't touch these tables. It's specifically what the Assistant
          (and CLI agent) has done: every question asked and every real MCP tool call it made
          answering it. If Assistant use is low, this legitimately looks empty — that's honest,
          not broken.
        </p>

        {error && <p className="app-banner-error">{error}</p>}

        <h3 className="activity-subheading">Agent runs</h3>
        {runs && runs.length === 0 && <p className="muted activity-empty">No agent runs yet — ask the Assistant something.</p>}
        {runs && runs.length > 0 && (
          <div className="activity-table-wrap">
            <table className="activity-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Persona</th>
                  <th>Provider / model</th>
                  <th>Question</th>
                  <th>Answer</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="tabular activity-td-ts">{fmtTs(r.ts)}</td>
                    <td>{r.persona}</td>
                    <td className="muted">{r.provider}{r.model ? ` · ${r.model}` : ''}</td>
                    <td className="activity-td-text">{truncate(r.question, 90)}</td>
                    <td className="activity-td-text muted">{truncate(r.answer, 90)}</td>
                    <td>
                      <span className={r.ok ? 'activity-status-ok' : 'activity-status-fail'}>
                        {r.ok ? 'OK' : 'FAILED'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h3 className="activity-subheading">MCP tool calls</h3>
        {audit && audit.length === 0 && <p className="muted activity-empty">No agent-originated tool calls yet.</p>}
        {audit && audit.length > 0 && (
          <div className="activity-table-wrap">
            <table className="activity-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Tool</th>
                  <th>Arguments</th>
                  <th>Latency</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td className="tabular activity-td-ts">{fmtTs(a.ts)}</td>
                    <td>{a.tool}</td>
                    <td className="activity-td-text muted tabular">{truncate(JSON.stringify(a.arguments), 70)}</td>
                    <td className="tabular">{a.latency_ms.toFixed(0)}ms</td>
                    <td>
                      <span className={a.ok ? 'activity-status-ok' : 'activity-status-fail'}>
                        {a.ok ? 'OK' : 'FAILED'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
