// `/vitest` subpath (not the bare package) both registers the jest-dom
// matchers on vitest's `expect` AND supplies the ambient type augmentation —
// see @testing-library/jest-dom's docs for why the plain import isn't enough
// under vitest.
import '@testing-library/jest-dom/vitest';

// Testing Library's auto-cleanup-after-each only self-registers when it finds
// a GLOBAL `afterEach` (i.e. `test.globals: true`), which this project's
// vitest config deliberately doesn't set (every test file imports its own
// hooks from 'vitest' instead) — so without this, DOM from one test leaks
// into the next and later `getByText` calls start matching duplicates.
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
afterEach(cleanup);

// jsdom doesn't implement ResizeObserver, but recharts' <ResponsiveContainer>
// (used by StressPanel, PeerScatter, CapitalChart, ConcentrationChart,
// RiskScorePanel) reaches for it unconditionally on mount — without this a
// smoke-render of any page pulling those in throws "ResizeObserver is not
// defined" before anything else in the tree gets a chance to run.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;
