// D1 (docs/audit/04-remediation-prompts.md): shared CSV export used by every
// exportable table and chart in the product. Every file this produces embeds
// the data vintage, source attribution and the G7 risk disclaimer as leading
// comment rows, and drops any column sourced from a non-redistributable feed
// (G3 — see config/sources.yaml `market_ohlc.license.redistributable: false`)
// once more than one bank's row is being exported.

export const RISK_DISCLAIMER =
  'Not investment advice. Not a supervisory rating. Not a regulatory capital calculation. ' +
  'Risk scores reflect structural resemblance to past bank failures, not a prediction of failure.';

export type CsvSource = 'fdic' | 'sec' | 'eba' | 'fed' | 'tiingo' | 'derived';

export interface CsvColumn<T> {
  key: string;
  label: string;
  value: (row: T) => string | number | null | undefined;
  /** Non-redistributable sources (currently only Tiingo) are stripped from any export of more than one row. */
  source?: CsvSource;
}

export interface CsvExportMeta {
  /** e.g. "2026Q1" or "SOD 2025" — the data vintage this export reflects. */
  vintage?: string;
  /** e.g. "FDIC Call Reports, EBA Transparency Exercise" */
  sourceLabel?: string;
}

function escapeCell(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '';
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function triggerDownload(filename: string, contents: string) {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Builds and downloads a CSV for an arbitrary row shape. Columns tagged
 * `source: 'tiingo'` are dropped once `rows.length > 1` — single-bank display
 * exports may still include the licensed field, bulk exports may not.
 */
export function downloadCsv<T>(
  filename: string,
  columns: CsvColumn<T>[],
  rows: T[],
  meta: CsvExportMeta = {},
): void {
  const bulk = rows.length > 1;
  const blockedSources = new Set<string>();
  const usable = columns.filter((c) => {
    if (bulk && c.source === 'tiingo') {
      blockedSources.add('Tiingo (commercial, non-redistributable — see config/sources.yaml)');
      return false;
    }
    return true;
  });

  const lines: string[] = [];
  lines.push(`# BankLens export — generated ${new Date().toISOString()}`);
  if (meta.vintage) lines.push(`# Data vintage: ${meta.vintage}`);
  if (meta.sourceLabel) lines.push(`# Source: ${meta.sourceLabel}`);
  if (blockedSources.size) {
    lines.push(`# Columns omitted (licensing): ${Array.from(blockedSources).join('; ')}`);
  }
  lines.push(`# ${RISK_DISCLAIMER}`);
  lines.push(usable.map((c) => escapeCell(c.label)).join(','));
  for (const row of rows) {
    lines.push(usable.map((c) => escapeCell(c.value(row))).join(','));
  }
  triggerDownload(filename, lines.join('\n'));
}

/** Convenience for exporting a chart's underlying series as (x, series...) rows. */
export function downloadChartDataCsv(
  filename: string,
  points: Record<string, string | number | null | undefined>[],
  meta: CsvExportMeta = {},
): void {
  if (!points.length) return;
  const keys = Object.keys(points[0]);
  const columns: CsvColumn<Record<string, string | number | null | undefined>>[] = keys.map((k) => ({
    key: k, label: k, value: (row) => row[k],
  }));
  downloadCsv(filename, columns, points, meta);
}
