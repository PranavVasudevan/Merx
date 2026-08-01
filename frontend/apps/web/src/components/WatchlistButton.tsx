import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { api } from '../api';
import './WatchlistButton.css';

export function WatchlistButton({ cert }: { cert: number }) {
  const [watched, setWatched] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.getWatchlist()
      .then((r) => { if (!cancelled) setWatched(r.items.some((w) => w.cert === cert)); })
      .catch(() => { if (!cancelled) setWatched(false); });
    return () => { cancelled = true; };
  }, [cert]);

  async function toggle() {
    if (watched === null || busy) return;
    setBusy(true);
    try {
      const r = watched ? await api.removeFromWatchlist(cert) : await api.addToWatchlist(cert);
      setWatched(r.items.some((w) => w.cert === cert));
    } catch {
      // leave state as-is — a transient failure shouldn't flip the button silently
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.button
      className={`watchlist-btn${watched ? ' watchlist-btn-active' : ''}`}
      onClick={toggle}
      disabled={watched === null || busy}
      whileTap={{ scale: 0.94 }}
      aria-pressed={watched === true}
    >
      <span className="watchlist-btn-star" aria-hidden="true">{watched ? '★' : '☆'}</span>
      {watched ? 'On watchlist' : 'Add to watchlist'}
    </motion.button>
  );
}
