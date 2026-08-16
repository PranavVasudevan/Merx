import { useEffect, useState } from 'react';
import { api } from '../api';
import { renderMarkdownLite } from '../markdownLite';
import type { AnnotationItem } from '../types';
import './AnnotationsPanel.css';

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** D7 — notes keyed on (user, cert, quarter), markdown-lite, shared across
 * users viewing the same bank. `quarter` optional: pin a note to a specific
 * landed quarter (rendered as an event marker on that bank's trend chart) or
 * leave it general. */
export function AnnotationsPanel({ cert, quarter }: { cert: number; quarter?: string | null }) {
  const [items, setItems] = useState<AnnotationItem[] | null>(null);
  const [draft, setDraft] = useState('');
  const [pinToQuarter, setPinToQuarter] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    api.getAnnotations(cert).then((r) => setItems(r.items)).catch(() => setItems([]));
  }

  useEffect(() => { load(); }, [cert]);

  async function submit() {
    const text = draft.trim();
    if (!text) return;
    setBusy(true);
    try {
      await api.addAnnotation(cert, text, pinToQuarter ? quarter ?? null : null);
      setDraft('');
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    try {
      await api.deleteAnnotation(cert, id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="panel">
      <h2>Notes</h2>
      <p className="muted annotations-subtitle">
        Shared analyst notes on this bank — **bold**, *italic* and links supported.
      </p>
      <div className="annotations-compose">
        <textarea
          className="annotations-textarea"
          placeholder="Add a note…"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="annotations-compose-row">
          {quarter && (
            <label className="annotations-pin-label">
              <input type="checkbox" checked={pinToQuarter} onChange={(e) => setPinToQuarter(e.target.checked)} />
              Pin to {quarter}
            </label>
          )}
          <button className="annotations-submit" onClick={submit} disabled={busy || !draft.trim()}>
            Add note
          </button>
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {items && items.length === 0 && <p className="muted annotations-empty">No notes yet.</p>}
      {items && items.length > 0 && (
        <div className="annotations-list">
          {items.map((a) => (
            <div key={a.id} className="annotations-item">
              <div className="annotations-item-meta">
                <span className="muted">{fmtDate(a.created_at)}</span>
                {a.quarter && <span className="annotations-quarter-badge">{a.quarter}</span>}
                <button className="annotations-remove" onClick={() => remove(a.id)} aria-label="Delete note">×</button>
              </div>
              {/* eslint-disable-next-line react/no-danger -- renderMarkdownLite escapes first, then applies a small fixed markup set */}
              <div className="annotations-item-body" dangerouslySetInnerHTML={{ __html: renderMarkdownLite(a.note_md) }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
