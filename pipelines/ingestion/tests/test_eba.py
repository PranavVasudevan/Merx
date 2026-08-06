"""Unit tests for the EBA connector that do NOT hit the network.

We test the pure parts: the CSV pivot (financials) and the stdlib .xlsx sheet
reader (institutions), the latter against a hand-built minimal .xlsx fixture. A
live smoke test against the real EBA endpoints is kept separate and opt-in so
CI stays hermetic — see the module docstring in sources/eba.py for how it was
verified live.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from banklens_ingestion.sources.eba import EbaSource  # noqa: E402


def _build_minimal_xlsx(rows: list[list[str]]) -> bytes:
    """A hand-built .xlsx with exactly the parts `_read_institutions_sheet` reads:
    xl/sharedStrings.xml (every cell value, in order of first appearance) and
    xl/worksheets/sheet1.xml (one <row> per input row, referencing the shared
    strings by index). Enough to unit-test the reader without a real EBA file."""
    strings: list[str] = []
    string_index: dict[str, int] = {}

    def sidx(s: str) -> int:
        if s not in string_index:
            string_index[s] = len(strings)
            strings.append(s)
        return string_index[s]

    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{chr(65 + c)}{r}" t="s"><v>{sidx(val)}</v></c>'
            for c, val in enumerate(row))
        sheet_rows.append(f'<row r="{r}">{cells}</row>')

    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", sst_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def test_read_institutions_sheet_skips_title_and_header_rows():
    xlsx = _build_minimal_xlsx([
        ["2025 EU-wide Transparency Exercise"],                       # title row (row 0)
        ["Country", "Desc_country", "LEI_Code", "Name"],              # header row
        ["AT", "Austria", "529900S9YO2JHTIIDG38", "BAWAG Group AG"],
        ["DE", "Germany", "7LTWFZYICNSX8D621K86", "DEUTSCHE BANK AKTIENGESELLSCHAFT"],
    ])
    out = EbaSource._read_institutions_sheet(xlsx)
    assert out == [
        {"country": "AT", "country_desc": "Austria", "lei": "529900S9YO2JHTIIDG38",
         "name": "BAWAG Group AG"},
        {"country": "DE", "country_desc": "Germany", "lei": "7LTWFZYICNSX8D621K86",
         "name": "DEUTSCHE BANK AKTIENGESELLSCHAFT"},
    ]


def test_read_institutions_sheet_skips_rows_with_no_lei():
    xlsx = _build_minimal_xlsx([
        ["title"],
        ["Country", "Desc_country", "LEI_Code", "Name"],
        ["AT", "Austria", "", "no LEI, e.g. a footnote row"],
    ])
    assert EbaSource._read_institutions_sheet(xlsx) == []


_CSV_HEADER = '"LEI_Code","NSA","Period","Item","Label","Amount","Sheet"\n'


def _csv_row(lei, nsa, period, item, label, amount, sheet):
    return f'"{lei}","{nsa}","{period}","{item}","{label}","{amount}","{sheet}"\n'


def test_pivot_financials_csv_scales_ratio_fields_to_percent():
    """Verified live: EBA reports CET1/Tier1/Total-capital/leverage ratios as raw
    fractions (0.1841 = 18.41%), unlike FDIC's already-percentage IDT1CER/RBCRWAJ.
    A downstream consumer treating an unscaled 0.18 as "18% CET1" vs "0.18% CET1"
    is exactly the class of bug this scaling exists to prevent."""
    text = _CSV_HEADER + _csv_row("LEI1", "DE", "202506", "2520140",
                                  "CET1 RATIO", "0.184187", "Capital")
    rows = EbaSource._pivot_financials_csv(text)
    assert len(rows) == 1
    assert abs(rows[0]["cet1_ratio"] - 18.4187) < 1e-9


def test_pivot_financials_csv_ignores_unmapped_item_codes():
    text = _CSV_HEADER + _csv_row("LEI1", "DE", "202506", "9999999",
                                  "Some unmapped line item", "42", "Other")
    assert EbaSource._pivot_financials_csv(text) == []


def test_pivot_financials_csv_groups_by_lei_and_period():
    text = (_CSV_HEADER
           + _csv_row("LEI1", "DE", "202506", "2521010", "Total Assets", "1000", "Assets")
           + _csv_row("LEI1", "DE", "202506", "2521216", "Total Equity", "80", "Liabilities")
           + _csv_row("LEI1", "DE", "202412", "2521010", "Total Assets", "950", "Assets"))
    rows = EbaSource._pivot_financials_csv(text)
    by_period = {r["period"]: r for r in rows}
    assert by_period["202506"]["total_assets"] == 1000.0
    assert by_period["202506"]["total_equity"] == 80.0
    assert by_period["202412"]["total_assets"] == 950.0
    assert "total_equity" not in by_period["202412"]   # not landed for that period


def test_source_metadata():
    s = EbaSource()
    assert s.name == "eba.transparency"
    assert s.license == "eba-open"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1; print(f"FAIL  {name}: {e}")
    print("\n" + ("OK - all tests passed" if not failures else f"{failures} failed"))
    sys.exit(1 if failures else 0)
