import { useEffect, useRef, useState } from 'react';
import { api, type BankSearchResult } from '../api';
import './BankSearch.css';

export function BankSearch({ onSelect }: { onSelect: (cert: number, name: string) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<BankSearchResult['banks']>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 8).then((r) => { setResults(r.banks); setOpen(true); }).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  return (
    <div className="bank-search" ref={boxRef}>
      <input
        className="bank-search-input"
        placeholder="Search a bank by name…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
      />
      {open && results.length > 0 && (
        <div className="bank-search-results">
          {results.map((b) => (
            <button
              key={b.cert}
              className="bank-search-result"
              onClick={() => { onSelect(b.cert, b.name); setQuery(b.name); setOpen(false); }}
            >
              <span className="bsr-name">{b.name}</span>
              <span className="muted bsr-meta">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
