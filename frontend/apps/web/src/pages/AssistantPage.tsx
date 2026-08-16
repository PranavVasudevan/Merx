import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import type { AssistantHistoryTurn, AssistantResult } from '../types';
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

// F16 — live tool-call progress as the SSE stream reports it. `preview`
// stays undefined between the "tool_call" event (call started) and the
// matching "tool_result" event (call finished) — the two always arrive in
// order for the same call, so "the last entry with no preview yet" is
// always the right one to fill in.
interface LiveToolCall {
  name: string;
  input: Record<string, unknown>;
  preview?: string;
  repeat?: boolean;
  citationUrl?: string | null;
}

// D12 — a citation link next to a tool call: click through to the exact
// dashboard page that shows the data backing that part of the answer,
// instead of asking the reader to trust the model's summary of it.
function CitationLink({ url }: { url: string | null | undefined }) {
  if (!url) return null;
  return (
    <Link className="assistant-citation-link" to={url} target="_blank" rel="noreferrer">
      View source →
    </Link>
  );
}

export function AssistantPage() {
  const [persona, setPersona] = useState(PERSONAS[0].key);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  // D12 — every answered turn so far in this conversation (rendered above the
  // input, oldest first), plus the plain-text transcript sent back to the
  // server as `history` on each new ask() so follow-up questions retain
  // context. Reset whenever the persona changes or "New conversation" is hit
  // — a persona swap mid-thread would silently change which tools/system
  // prompt are answering follow-ups, so treat it as a fresh conversation.
  const [turns, setTurns] = useState<{ question: string; result: AssistantResult }[]>([]);
  const [history, setHistory] = useState<AssistantHistoryTurn[]>([]);
  const [liveCalls, setLiveCalls] = useState<LiveToolCall[]>([]);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => { if (timerRef.current) window.clearInterval(timerRef.current); }, []);

  function newConversation() {
    if (loading) return;
    setTurns([]);
    setHistory([]);
    setError(null);
  }

  function selectPersona(key: string) {
    if (loading) return;
    setPersona(key);
    setTurns([]);
    setHistory([]);
    setError(null);
  }

  async function ask() {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setLiveCalls([]);
    setStatusMessage(null);
    setElapsed(0);
    setQuestion('');
    timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    try {
      for await (const evt of api.streamAssistantAsk(persona, q, history)) {
        if (evt.event === 'tool_call') {
          const { name, input, repeat } = evt.data;
          setLiveCalls((calls) => [...calls, { name, input, repeat }]);
        } else if (evt.event === 'tool_result') {
          const { preview, citation_url: citationUrl } = evt.data;
          setLiveCalls((calls) => {
            const next = [...calls];
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].preview === undefined) { next[i] = { ...next[i], preview, citationUrl }; break; }
            }
            return next;
          });
        } else if (evt.event === 'final') {
          setStatusMessage('Writing the final answer…');
        } else if (evt.event === 'timeout') {
          setStatusMessage(evt.data.message);
        } else if (evt.event === 'error') {
          setError(evt.data.request_id ? `${evt.data.error} (request: ${evt.data.request_id})` : evt.data.error);
        } else if (evt.event === 'result') {
          setTurns((prev) => [...prev, { question: q, result: evt.data }]);
          setHistory(evt.data.history);
        }
      }
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
          Runs on the $0 local model (Ollama) by default, which means <strong>this can take a
          while</strong> — you'll see each tool call appear below as it happens, and the server
          gives up gracefully (returning whatever it found so far) rather than hanging forever.
        </p>

        <div className="assistant-personas">
          {PERSONAS.map((p) => (
            <button
              key={p.key}
              className={`assistant-persona${persona === p.key ? ' assistant-persona-active' : ''}`}
              onClick={() => selectPersona(p.key)}
              disabled={loading}
            >
              <span className="assistant-persona-label">{p.label}</span>
              <span className="muted assistant-persona-blurb">{p.blurb}</span>
            </button>
          ))}
        </div>

        {turns.length > 0 && (
          <div className="assistant-thread">
            {turns.map((t, i) => (
              <div className="assistant-turn" key={i}>
                <div className="assistant-turn-question">{t.question}</div>
                <motion.div
                  className="assistant-result"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  {t.result.partial && (
                    <p className="assistant-partial-banner">
                      Partial answer — the server-side deadline was reached before the model finished
                      reasoning. What's below is real data it had already retrieved, not a guess.
                    </p>
                  )}
                  <div className="assistant-answer">{t.result.answer}</div>
                  <div className="muted assistant-meta">
                    {t.result.provider} · {t.result.turns} turn{t.result.turns === 1 ? '' : 's'} ·{' '}
                    {t.result.tool_calls.length} tool call{t.result.tool_calls.length === 1 ? '' : 's'}
                  </div>

                  {t.result.tool_calls.length > 0 && (
                    <div className="assistant-tool-calls">
                      <h3 className="assistant-tool-calls-heading">Tool calls</h3>
                      {t.result.tool_calls.map((tc, j) => (
                        <div className="assistant-tool-call" key={j}>
                          <div className="assistant-tool-call-name tabular">
                            {tc.name}({JSON.stringify(tc.arguments)})
                          </div>
                          <div className="muted assistant-tool-call-preview">{tc.result_preview}</div>
                          <CitationLink url={tc.citation_url} />
                        </div>
                      ))}
                    </div>
                  )}
                </motion.div>
              </div>
            ))}
          </div>
        )}

        <div className="assistant-input-row">
          <textarea
            className="assistant-input"
            placeholder={turns.length > 0 ? 'Ask a follow-up…' : 'Ask a question in plain English…'}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
            rows={3}
          />
          <button className="assistant-ask-btn" onClick={ask} disabled={loading || !question.trim()}>
            {loading ? `Working… ${elapsed}s` : turns.length > 0 ? 'Ask follow-up' : 'Ask'}
          </button>
          {turns.length > 0 && (
            <button className="assistant-new-btn" onClick={newConversation} disabled={loading}>
              New conversation
            </button>
          )}
        </div>

        {loading && (
          <div className="assistant-live">
            <p className="muted assistant-waiting">
              {statusMessage
                ?? `The ${PERSONAS.find((p) => p.key === persona)?.label} is reasoning over real MCP tool calls — live progress below as each one completes.`}
            </p>
            {liveCalls.length > 0 && (
              <div className="assistant-tool-calls">
                {liveCalls.map((tc, i) => (
                  <div className="assistant-tool-call" key={i}>
                    <div className="assistant-tool-call-name tabular">
                      {tc.name}({JSON.stringify(tc.input)}){tc.repeat ? ' (cached)' : ''}
                      {tc.preview === undefined && <span className="assistant-tool-call-pending"> …</span>}
                    </div>
                    {tc.preview !== undefined && (
                      <>
                        <div className="muted assistant-tool-call-preview">{tc.preview}</div>
                        <CitationLink url={tc.citationUrl} />
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {error && <p className="app-banner-error">{error}</p>}
      </div>
    </div>
  );
}
