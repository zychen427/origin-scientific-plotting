"""Explicit, numeric Excel range import with preview and read-back verification."""
import json
import math
import os

from ..app import mcp
from ..labtalk_safe import windows_path, labtalk_name
from ..origin_connection import workbook_names
from .worksheet import create_worksheet, set_worksheet_data, get_worksheet_data


def _read_excel(path, sheet, cell_range, *, summary_only=False):
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.cell import range_boundaries
    except ImportError as exc:
        raise RuntimeError("Precise Excel import requires openpyxl; install server/requirements.txt.") from exc
    if not path.lower().endswith((".xlsx", ".xlsm")) or not os.path.isfile(path):
        raise ValueError("An existing .xlsx or .xlsm file is required for precise import.")
    try:
        c1, r1, c2, r2 = range_boundaries(cell_range)
        if not all(isinstance(v, int) and v > 0 for v in (c1, r1, c2, r2)) or c2 < c1 or r2 < r1:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("cell_range must be an explicit finite rectangle, e.g. B2:D101.")
    if (c2-c1+1)*(r2-r1+1) > 1000000:
        raise ValueError("Selection exceeds the one million cell limit.")
    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"Excel sheet not found: {sheet!r}; available: {wb.sheetnames}")
        ws = wb[sheet]
        if r2 > ws.max_row or c2 > ws.max_column:
            raise ValueError("Selected range extends beyond the worksheet's used range.")
        cols = None if summary_only else [[] for _ in range(c2-c1+1)]
        missing = [0] * (c2-c1+1)
        first_rows = []
        for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
            preview = []
            for i, cell in enumerate(row):
                v = cell.value
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
                    raise ValueError(f"{cell.coordinate} is not a finite numeric value or blank; formulas and text are not imported.")
                missing[i] += v is None
                if cols is not None: cols[i].append(v)
                if len(first_rows)<5: preview.append(v)
            if len(first_rows)<5: first_rows.append(preview)
        if summary_only:
            return {'rows':r2-r1+1,'columns':c2-c1+1,'missing_per_column':missing,'first_rows':first_rows}
        return cols
    finally:
        wb.close()


@mcp.tool()
def preview_excel_range(file_path: str, sheet: str, cell_range: str) -> str:
    """Inspect a rectangular numeric Excel range; blank cells stay blank. Formulas and text are rejected.

    Provide an exact worksheet name and rectangle such as B2:D101, excluding headers.
    Only .xlsx/.xlsm are supported. No Origin state is changed.
    """
    path = windows_path(file_path, "file_path")
    summary = _read_excel(path, sheet, cell_range, summary_only=True)
    return json.dumps({"file": path, "sheet": sheet, "range": cell_range, **summary}, ensure_ascii=False)


@mcp.tool()
def import_excel_range(file_path: str, sheet: str, cell_range: str, book_name: str) -> str:
    """Import an explicit numeric .xlsx/.xlsm rectangle into a new Origin workbook and verify every value.

    Range excludes headers; formulas, text, dates and booleans are rejected. No original file is modified.
    Missing values remain missing. If a write fails, a partially populated new workbook may remain.
    """
    path = windows_path(file_path, "file_path")
    cols = _read_excel(path, sheet, cell_range)
    name = labtalk_name(book_name, "book_name")
    if name in workbook_names():
        raise ValueError(f"Workbook {name} already exists; import was not attempted.")
    created = json.loads(create_worksheet(name))
    book = created["name"]
    try:
        set_worksheet_data(book, "Sheet1", json.dumps(cols, allow_nan=False))
        got = json.loads(get_worksheet_data(book, "Sheet1"))["columns"]
        for c, expected in enumerate(cols):
            if c >= len(got) or len(got[c]) < len(expected):
                raise RuntimeError("Imported dimensions differ from the selected range.")
            for r, value in enumerate(expected):
                actual = got[c][r]
                if (value is None and actual is not None) or (value is not None and (actual is None or actual != value)):
                    raise RuntimeError(f"Read-back mismatch at selection row {r+1}, column {c+1}.")
    except Exception as exc:
        raise RuntimeError(f"Import or verification failed; inspect new workbook {book}: {exc}") from exc
    return json.dumps({"name": book, "sheet": "Sheet1", "source_file": path,
                       "source_sheet": sheet, "source_range": cell_range,
                       "rows": len(cols[0]), "columns": len(cols), "verified": True}, ensure_ascii=False)
