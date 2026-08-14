import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { api } from './api';

// D3 (docs/audit/04-remediation-prompts.md): a global "which landed quarter
// am I looking at" selection, persisted in the URL's `?quarter=` search param
// so a link to a page reproduces the same quarter it was copied from (D8's
// pattern, applied here first). `null` means "latest" — the unchanged default
// for every consumer, so a page that never reads this context behaves exactly
// as before.
interface QuarterContextValue {
  quarter: string | null;
  quarters: string[];
  latest: string | null;
  setQuarter: (q: string | null) => void;
  isLatest: boolean;
}

const QuarterContext = createContext<QuarterContextValue | null>(null);

export function QuarterProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const [quarters, setQuarters] = useState<string[]>([]);
  const [latest, setLatest] = useState<string | null>(null);
  const [quarter, setQuarterState] = useState<string | null>(() => searchParams.get('quarter'));

  useEffect(() => {
    api.quarters().then((r) => { setQuarters(r.quarters); setLatest(r.latest); }).catch(() => {});
  }, []);

  // react-router Links don't carry the current search string to a new
  // pathname by default, so a plain NavShell click would silently drop the
  // selection. Re-append it after every navigation rather than threading a
  // `search` prop through every nav link.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (quarter && quarter !== latest && searchParams.get('quarter') !== quarter) {
      const next = new URLSearchParams(searchParams);
      next.set('quarter', quarter);
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  function setQuarter(q: string | null) {
    setQuarterState(q);
    const next = new URLSearchParams(searchParams);
    if (q && q !== latest) next.set('quarter', q); else next.delete('quarter');
    setSearchParams(next, { replace: true });
  }

  return (
    <QuarterContext.Provider value={{ quarter, quarters, latest, setQuarter, isLatest: !quarter || quarter === latest }}>
      {children}
    </QuarterContext.Provider>
  );
}

export function useQuarter(): QuarterContextValue {
  const ctx = useContext(QuarterContext);
  if (!ctx) throw new Error('useQuarter must be used within a QuarterProvider');
  return ctx;
}

/** Formats a REPDTE (YYYYMMDD) as "2026Q1" for display. */
export function fmtQuarter(repdte: string): string {
  const y = repdte.slice(0, 4);
  const m = Number(repdte.slice(4, 6));
  const q = Math.ceil(m / 3);
  return `${y}Q${q}`;
}
