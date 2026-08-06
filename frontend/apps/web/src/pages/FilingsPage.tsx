import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import type { FilingSearchResult, FilingsCoverageResult } from '../types';
import './FilingsPage.css';

const EXAMPLE_QUERIES = [
  'commercial real estate concentration risk',
  'uninsured deposit outflow',
  'interest rate risk on securities portfolio',
  'cybersecurity and data breach exposure',
];

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export function FilingsPage() {
  const [coverage, setCoverage] = useState<FilingsCoverageResult | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FilingSearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.filingsCoverage()
      .then((r) => { setCoverage(r); setCoverageError(null); })
      .catch((e: Error) => setCoverageError(e.message));
  }, []);

  function runSearch(q: string) {
    if (!q.trim()) return;
    setLoading(true);
    api.searchFilings(q, 10)
      .then((r) => { setResults(r.results); setError(null); })
      .catch((e: Error) => { setError(e.message); setResults(null); })
      .finally(() => setLoading(false));
  }

  return (
    <div className="filings-page">
      <div className="panel">
        <h2>Filing risk-factor search</h2>
        <p className="muted filings-subtitle">
          Feature 17, Tier 6 capstone — real semantic search over SEC 10-K "Item 1A
          Risk Factors" text, embedded with a local nomic-embed-text model and
          matched by pgvector cosine similarity. Every result quotes the filing's
          exact language, not a paraphrase.
        </p>

        {coverageError && <p className="app-banner-error">{coverageError}</p>}
        {coverage && (
          <div className="filings-coverage">
            <span className="tabular">{coverage.filers} filer{coverage.filers === 1 ? '' : 's'}</span>
            <span className="muted"> · </span>
            <span className="tabular">{coverage.chunks.toLocaleString()} chunks landed</span>
            <span className="muted"> — a real but bounded, growing subset of the population
              (largest banks by assets, confidently matched to a SEC filer, with a clean
              Item 1A extraction). Not every bank has a searchable filing yet.</span>
          </div>
        )}

        <form className="filings-search-form" onSubmit={(e) => { e.preventDefault(); runSearch(query); }}>
          <input
            className="filings-search-input"
            placeholder="Search real risk-factor language…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="filings-search-btn" type="submit" disabled={loading}>
            {loading ? 'Searching…' : 'Search'}
          </button>
        </form>
        <div className="filings-examples">
          <span className="muted">Try:</span>
          {EXAMPLE_QUERIES.map((q) => (
            <button key={q} className="filings-example-chip" onClick={() => { setQuery(q); runSearch(q); }}>
              {q}
            </button>
          ))}
        </div>
        {error && <p className="app-banner-error">{error}</p>}
      </div>

      {results && (
        <div className="panel">
          <h2>{results.length} result{results.length === 1 ? '' : 's'}</h2>
          {results.length === 0 && (
            <p className="muted">No landed filings yet, or nothing close enough to this query.</p>
          )}
          <div className="filings-results">
            {results.map((r) => (
              <div className="filings-result" key={`${r.cik}-${r.chunk_index}`}>
                <div className="filings-result-head">
                  {r.cert ? (
                    <Link className="filings-result-name" to={`/bank/${r.cert}`}>{r.name}</Link>
                  ) : (
                    <span className="filings-result-name">{r.name}</span>
                  )}
                  {r.ticker && <span className="muted filings-result-ticker">{r.ticker}</span>}
                  <span className="muted filings-result-date">10-K filed {r.filing_date}</span>
                  <span className="tabular filings-result-sim">{fmtPct(r.similarity)} match</span>
                </div>
                <p className="filings-result-text">"{r.chunk_text}"</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
