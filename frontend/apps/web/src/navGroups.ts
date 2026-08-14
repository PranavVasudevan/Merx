// The single source of truth for BankLens's routed pages — shared by NavShell (the
// visible nav bar) and CommandPalette (Cmd/Ctrl+K fuzzy jump), so a new route only
// needs to be added in one place instead of drifting into two hardcoded lists.
export interface NavLink { to: string; label: string }
export interface NavGroup { label: string; links: NavLink[] }

export const NAV_GROUPS: NavGroup[] = [
  { label: 'Explore', links: [
    { to: '/', label: 'Overview' },
    { to: '/screener', label: 'Screener' },
    { to: '/compare', label: 'Compare' },
  ] },
  { label: 'Analyze', links: [
    { to: '/earnings', label: 'Earnings' },
    { to: '/credit', label: 'Credit' },
    { to: '/funding', label: 'Funding' },
    { to: '/trends', label: 'Trends' },
    { to: '/filing-diff', label: 'Filing Diff' },
    { to: '/briefing', label: 'Briefing' },
  ] },
  { label: 'Visualize', links: [
    { to: '/heatmap', label: 'Heatmap' },
    { to: '/treemap', label: 'Treemap' },
    { to: '/distributions', label: 'Distributions' },
    { to: '/market', label: 'Market' },
  ] },
  { label: 'Governance', links: [
    { to: '/clusters', label: 'Clusters' },
    { to: '/model', label: 'Model' },
  ] },
  { label: 'Geography', links: [
    { to: '/geography', label: 'Branch Map' },
    { to: '/market-share', label: 'Market Share' },
  ] },
  { label: 'Simulate', links: [
    { to: '/network', label: 'Network' },
    { to: '/stress-lab', label: 'Stress Lab' },
  ] },
  { label: 'Research', links: [
    { to: '/filings', label: 'Filings' },
  ] },
  { label: 'My work', links: [
    { to: '/watchlist', label: 'Watchlist' },
  ] },
  { label: 'Tools', links: [
    { to: '/assistant', label: 'Assistant' },
    { to: '/activity', label: 'Activity' },
  ] },
];

/** Flattened for search UIs (command palette) that don't need group headers. */
export const ALL_NAV_LINKS: (NavLink & { group: string })[] = NAV_GROUPS.flatMap(
  (g) => g.links.map((l) => ({ ...l, group: g.label })),
);
