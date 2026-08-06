import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { api, type BankSearchResult } from '../api';
import { ALL_NAV_LINKS } from '../navGroups';

// Global Cmd/Ctrl+K jump — routes come from navGroups.ts (the same list NavShell
// renders, not a hardcoded duplicate), and bank lookup reuses api.searchBanks(),
// the exact call BankSearch.tsx already makes. No fake/mock entries: everything
// listed here is either a real route or a real bank from the Gold layer.
export function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [banks, setBanks] = useState<BankSearchResult['banks']>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsOpen((v) => !v);
      } else if (e.key === 'Escape') {
        setIsOpen(false);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setBanks([]);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  useEffect(() => {
    if (query.trim().length < 2) { setBanks([]); return; }
    const t = setTimeout(() => {
      api.searchBanks(query, undefined, 5).then((r) => setBanks(r.banks)).catch(() => setBanks([]));
    }, 200);
    return () => clearTimeout(t);
  }, [query]);

  if (!isOpen) return null;

  const q = query.trim().toLowerCase();
  const routeMatches = q.length === 0
    ? ALL_NAV_LINKS
    : ALL_NAV_LINKS.filter((l) => l.label.toLowerCase().includes(q) || l.group.toLowerCase().includes(q));

  function go(path: string) {
    navigate(path);
    setIsOpen(false);
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-24 px-4 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onClick={() => setIsOpen(false)}
      >
        <motion.div
          className="glass-panel w-full max-w-xl overflow-hidden"
          initial={{ opacity: 0, y: -8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.98 }}
          transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="border-b border-border p-3">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Jump to a page or search a bank by name…"
              className="w-full bg-transparent text-base font-medium text-primary outline-none placeholder:text-muted"
            />
          </div>

          <div className="max-h-96 overflow-y-auto p-2">
            {banks.length > 0 && (
              <div className="mb-1">
                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">Banks</div>
                {banks.map((b) => (
                  <button
                    key={b.cert}
                    onClick={() => go(`/bank/${b.cert}`)}
                    className="flex w-full items-center justify-between rounded-panel px-3 py-2 text-left text-sm
                               text-primary transition-colors hover:bg-surface-2"
                  >
                    <span className="font-medium">{b.name}</span>
                    <span className="text-xs text-muted">${b.assets_b.toFixed(1)}B · {b.state ?? '—'}</span>
                  </button>
                ))}
              </div>
            )}

            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">Pages</div>
            {routeMatches.length === 0 ? (
              <div className="px-3 py-4 text-center text-sm text-muted">No matching pages.</div>
            ) : (
              routeMatches.map((link) => (
                <button
                  key={link.to}
                  onClick={() => go(link.to)}
                  className="flex w-full items-center justify-between rounded-panel px-3 py-2 text-left text-sm
                             text-primary transition-colors hover:bg-surface-2"
                >
                  <span className="font-medium">{link.label}</span>
                  <span className="rounded-panel-sm border border-border px-1.5 py-0.5 text-[10px] text-muted">
                    {link.group}
                  </span>
                </button>
              ))
            )}
          </div>

          <div className="flex items-center justify-between border-t border-border bg-surface-2 px-3 py-2 text-[10px] text-muted">
            <span>ENTER TO NAVIGATE</span>
            <span>ESC TO CLOSE</span>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
