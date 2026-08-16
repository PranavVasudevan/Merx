import { useId, useState } from 'react';
import { ExportCsvButton } from './ExportCsvButton';
import type { CsvColumn, CsvExportMeta, CsvSource } from '../csvExport';
import './Figure.css';

/**
 * A column definition shared by the underlying-data <table> AND the CSV
 * export — one source of truth per chart instead of two hand-kept-in-sync
 * lists. `value` defaults to `row[key]` when omitted (the common case where
 * the table key and the row property name match).
 */
export interface FigureColumn<T> {
  key: string;
  label: string;
  value?: (row: T) => string | number | null | undefined;
  /** Passed through to CsvColumn — see csvExport.ts's non-redistributable-source stripping. */
  source?: CsvSource;
  /** Table-only formatting override (e.g. "$1.2B"); CSV always uses the raw `value`. */
  format?: (row: T) => string;
}

export interface FigureProps<T extends object> {
  /**
   * Required, real description of what the chart shows — e.g. "CET1 surface
   * across deposit outflow and rate shock, colored by pass/fail against the
   * regulatory minimum". Applied as the chart region's aria-label so a
   * screen reader announces what the (otherwise opaque canvas/SVG) region
   * is, and also anchors the figure itself for landmark navigation.
   */
  ariaLabel: string;
  /** Rendered as <figcaption> — the visible title/caption above the chart. */
  caption?: React.ReactNode;
  /** The chart itself (recharts <ResponsiveContainer>, <EChart>, a lightweight-charts container div, ...). */
  children: React.ReactNode;
  /** Same rows the chart was built from — the data-table toggle and CSV export both read from this single array. */
  rows: T[];
  columns: FigureColumn<T>[];
  /** Passed to ExportCsvButton. */
  filename: string;
  csvMeta?: CsvExportMeta;
  className?: string;
  /** Hide the CSV button (e.g. a chart whose parent already renders one for a wider dataset). Table toggle still shows. */
  hideDownload?: boolean;
}

/**
 * E14 — shared chart wrapper: every chart it's applied to gets a data-table
 * fallback, a CSV download, and an aria-label, in one place instead of
 * reimplemented per chart.
 *
 * Accessibility tradeoff, stated rather than overclaimed: recharts (SVG) and
 * especially ECharts/lightweight-charts (canvas) data points are NOT
 * individually keyboard-focusable — none of the three libraries in this app
 * expose per-point tab stops out of the box, and wiring that up generically
 * across three different rendering models is out of scope here. What IS
 * fully keyboard-navigable is the toggled <table>: it's a real HTML table,
 * reachable by Tab (the toggle button, then normal document/table
 * navigation) and readable cell-by-cell by any screen reader's native table
 * navigation (e.g. NVDA/JAWS Ctrl+Alt+arrows). That covers the substance of
 * "reachable and readable without vision of the canvas" — a sighted-only
 * canvas/SVG chart becomes a fully non-visual-accessible table on demand.
 */
export function Figure<T extends object>({
  ariaLabel, caption, children, rows, columns, filename, csvMeta, className, hideDownload,
}: FigureProps<T>) {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();

  // `row[c.key]` has no static type when T doesn't declare an index
  // signature (most callers pass a concrete interface, e.g. LegContribution)
  // — this generic fallback is only reached when a caller omits `value`,
  // in which case `key` is documented to name a real property on T.
  const byKey = (row: T, key: string): string | number | null | undefined =>
    (row as Record<string, unknown>)[key] as string | number | null | undefined;

  const csvColumns: CsvColumn<T>[] = columns.map((c) => ({
    key: c.key,
    label: c.label,
    value: c.value ?? ((row: T) => byKey(row, c.key)),
    source: c.source,
  }));

  return (
    <figure className={`figure${className ? ` ${className}` : ''}`} aria-label={ariaLabel}>
      <div className="figure-toolbar">
        <button
          type="button"
          className="figure-toggle-btn"
          aria-pressed={showTable}
          aria-controls={tableId}
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? 'Show chart' : 'Show data table'}
        </button>
        {!hideDownload && (
          <ExportCsvButton filename={filename} columns={csvColumns} rows={rows} meta={csvMeta} />
        )}
      </div>

      <div className="figure-body">
        {/*
          Both views stay mounted; only the `hidden` attribute toggles which
          one is visible/in the a11y tree. This is deliberate, not just a
          style choice: recharts/ECharts/lightweight-charts all attach an
          imperative chart instance to a real DOM node (see CandlestickChart,
          whose lightweight-charts `createChart()` call lives in a parent
          effect, not a component that would naturally remount). Swapping
          between chart and table with a conditional `{showTable ? a : b}`
          would unmount that node out from under the library on every toggle
          and never recreate it going back, leaving a blank chart. `hidden`
          removes it from layout and from the accessibility tree/tab order
          without tearing down the underlying instance.
        */}
        <div className="figure-table-scroll" id={tableId} tabIndex={0} hidden={!showTable}>
          <table className="figure-table">
            <caption className="sr-only">{ariaLabel}</caption>
            <thead>
              <tr>
                {columns.map((c) => <th key={c.key} scope="col">{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td className="figure-table-empty" colSpan={columns.length}>No data</td></tr>
              ) : rows.map((row, i) => (
                // eslint-disable-next-line react/no-array-index-key -- rows have no stable id in the generic shape
                <tr key={i}>
                  {columns.map((c) => {
                    const raw = c.value ? c.value(row) : byKey(row, c.key);
                    const text = c.format ? c.format(row) : (raw === null || raw === undefined ? '—' : String(raw));
                    return <td key={c.key}>{text}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* role="img" + the same aria-label: the chart region reads as one
            opaque-but-labeled image to a screen reader instead of exposing
            (and letting AT get lost in) every internal SVG/canvas node. */}
        <div className="figure-chart" role="img" aria-label={ariaLabel} hidden={showTable}>
          {children}
        </div>
      </div>

      {caption && <figcaption className="figure-caption">{caption}</figcaption>}
    </figure>
  );
}
