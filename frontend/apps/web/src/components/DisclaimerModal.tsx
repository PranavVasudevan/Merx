import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { RISK_DISCLAIMER } from '../csvExport';

const ACK_KEY = 'banklens.disclaimer.ack.v1';

// G7 — first-run gate: every risk score, capital-adequacy verdict and
// merger-concentration screen in the product needs the reader to have seen
// this once, up front, rather than relying on them to find the footer.
// localStorage-gated so it shows once per browser until acknowledged.
export function DisclaimerModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(localStorage.getItem(ACK_KEY) !== '1');
  }, []);

  function acknowledge() {
    localStorage.setItem(ACK_KEY, '1');
    setOpen(false);
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            className="glass-panel w-full max-w-lg p-6"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.85, 0, 0.15, 1] }}
          >
            <h2 className="mb-3 text-lg font-semibold text-body">Before you use BankLens</h2>
            <p className="mb-3 text-sm text-dim">{RISK_DISCLAIMER}</p>
            <p className="mb-3 text-xs text-faint">
              This applies to every risk score, capital-adequacy verdict and merger-concentration
              screen in the product, wherever it's shown.
            </p>
            {/* D14 — first-run tour: what the population is + what the data vintage is,
                so scope and staleness are visible before the first number, not discovered later. */}
            <p className="mb-3 text-xs text-faint">
              The population is FDIC-insured US banks plus significant EU/EEA institutions
              reporting to the EBA — every figure traces back to a real, public FDIC BankFind,
              SEC EDGAR or EBA filing (see the "verify this number" link on any metric). Data
              lands on a real vintage, not "live" — check the freshness strip in the footer for
              exactly how current each source is before relying on a number.
            </p>
            <button
              type="button"
              onClick={acknowledge}
              className="rounded-panel bg-cat-blue px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              I understand — continue
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
