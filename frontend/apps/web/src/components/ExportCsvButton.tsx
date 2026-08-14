import { downloadCsv, type CsvColumn, type CsvExportMeta } from '../csvExport';
import './ExportCsvButton.css';

export interface ExportCsvButtonProps<T> {
  filename: string;
  columns: CsvColumn<T>[];
  rows: T[];
  meta?: CsvExportMeta;
  label?: string;
  disabled?: boolean;
}

/** D1 — the one reusable "Download CSV" control every table in the product attaches. */
export function ExportCsvButton<T>({ filename, columns, rows, meta, label = 'Download CSV', disabled }: ExportCsvButtonProps<T>) {
  return (
    <button
      type="button"
      className="export-csv-btn"
      disabled={disabled || rows.length === 0}
      onClick={() => downloadCsv(filename, columns, rows, meta)}
      title={rows.length === 0 ? 'Nothing to export yet' : `Download ${rows.length} row(s) as CSV`}
    >
      ⭳ {label}
    </button>
  );
}
