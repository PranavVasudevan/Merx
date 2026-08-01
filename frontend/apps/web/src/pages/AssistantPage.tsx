import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { api } from '../api';
import type { AssistantResult } from '../types';
import './AssistantPage.css';

// Mirrors services/agents/src/banklens_agents/personas.py's PERSONAS keys —
// no "list personas" endpoint exists yet, so this is presentation metadata
// only, kept in sync by hand until/unless one gets added.
const PERSONAS: { key: string; label: string; blurb: string }[] = [
  { key: 'risk_analyst', label: 'Risk Analyst', blurb: 'Concentration risk and deposit-flight/run risk.' },
  { key: 'filings_analyst', label: 'Filings Analyst', blurb: "What changed in a bank's filings and why it matters." },
  { key: 'ma_scout', label: 'M&A Scout', blurb: 'Acquisition/partnership fit.' },
  { key: 'macro_stress', label: 'Macro / Stress', blurb: 'Capital resilience under stress and market context.' },
  { key: 'generalist', label: 'Generalist', blurb: 'Every tool — whichever fits the question.' },
];

export function AssistantPage() {
  const [persona, setPersona] = useState(PERSONAS[0].key);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<AssistantResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => { if (timerRef.current) window.clearInterval(timerRef.current); }, []);

  async function ask() {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setElapsed(0);
    timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    try {
      const r = await api.askAssistant(persona, q);
      setResult(r);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setLoading(false);
      if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null; }
    }
  }

  return (
    <div className="assistant-page">
      <div className="panel">
        <h2>Assistant</h2>
        <p className="muted assistant-note">
          Real MCP tool-calling agents, not a chatbot skin over static text — each persona reasons
          over a focused subset of the same 12 tools the dashboard uses, live against real data.
          Runs on the $0 local model (Ollama) by default, which means <strong>this can take several
          minutes</strong>, especially for a persona that needs multiple tool calls to answer.
        </p>

        <div className="assistant-personas">
          {PERSONAS.map((p) => (
            <button
              key={p.key}
              className={`assistant-persona${persona === p.key ? ' assistant-persona-active' : ''}`}
              onClick={() => setPersona(p.key)}
              disabled={loading}
            >
              <span className="assistant-persona-label">{p.label}</span>
              <span className="muted assistant-persona-blurb">{p.blurb}</span>
            </button>
          ))}
        </div>

        <div className="assistant-input-row">
          <textarea
            className="assistant-input"
            placeholder="Ask a question in plain English…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
            rows={3}
          />
          <button className="assistant-ask-btn" onClick={ask} disabled={loading || !question.trim()}>
            {loading ? `Working… ${elapsed}s` : 'Ask'}
          </button>
        </div>

        {loading && (
          <p className="muted assistant-waiting">
            The {PERSONAS.find((p) => p.key === persona)?.label} is reasoning over real MCP tool
            calls — no progress bar exists for this yet, but it hasn't failed just because it's slow.
          </p>
        )}

        {error && <p className="app-banner-error">{error}</p>}

        {result && (
          <motion.div
            className="assistant-result"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <div className="assistant-answer">{result.answer}</div>
            <div className="muted assistant-meta">
              {result.provider} · {result.turns} turn{result.turns === 1 ? '' : 's'} ·{' '}
              {result.tool_calls.length} tool call{result.tool_calls.length === 1 ? '' : 's'}
            </div>

            {result.tool_calls.length > 0 && (
              <div className="assistant-tool-calls">
                <h3 className="assistant-tool-calls-heading">Tool calls</h3>
                {result.tool_calls.map((tc, i) => (
                  <div className="assistant-tool-call" key={i}>
                    <div className="assistant-tool-call-name tabular">
                      {tc.name}({JSON.stringify(tc.arguments)})
                    </div>
                    <div className="muted assistant-tool-call-preview">{tc.result_preview}</div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}
