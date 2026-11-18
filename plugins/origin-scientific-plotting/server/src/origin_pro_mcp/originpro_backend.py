"""Official originpro calls inside an explicitly isolated native worker."""
from __future__ import annotations

import importlib
import os
import threading

_LOCK = threading.RLock()
_API = None


def _enabled() -> bool:
    return (os.environ.get('ORIGIN_PRO_MCP_WORKER') == '1' and
            os.environ.get('ORIGIN_PRO_MCP_BACKEND', 'originpro') == 'originpro')


def _ensure_loaded():
    global _API
    with _LOCK:
        if _API is None:
            _API = importlib.import_module("originpro")
        return _API


def is_available() -> bool:
    """Whether the experimental API is installed and enabled without touching Origin."""
    if not _enabled():
        return False
    # An enabled native worker must not silently switch after a binding failure.
    get_api()
    return True


def get_api():
    """Return originpro, bound to the current MCP session's Origin instance."""
    if not _enabled():
        raise RuntimeError(
            "The originpro object backend is disabled by default outside a "
            "worker configured for originpro. The legacy thread-global adapter "
            "cannot be enabled."
        )
    api = _ensure_loaded()
    # The originpro module may only be used by a worker whose own application
    # was created by originpro itself. Never patch module-global po proxies.
    from .origin_connection import get_origin
    from .originpro_native import NativeOrigin
    origin = get_origin()
    if not isinstance(origin, NativeOrigin) or origin.api is not api:
        raise RuntimeError('originpro is not bound to this worker-owned Origin.')
    return api


def capability() -> dict:
    if not _enabled():
        from importlib.metadata import PackageNotFoundError, version
        try:
            package_version = version("originpro")
            installed = True
        except PackageNotFoundError:
            package_version = None
            installed = False
        return {"available": False, "enabled": False, "installed": installed,
                "package": "originpro", "package_version": package_version,
                "reason": "This worker is not configured for the originpro backend."}
    try:
        api = get_api()
        from importlib.metadata import version
        return {"available": True, "package": "originpro",
                "package_version": version("originpro"),
                "object_api": True, "connection": "worker_owned_originext",
                "enabled": True, "installed": True}
    except Exception as exc:
        return {"available": False, "package": "originpro",
                "enabled": True, "installed": False,
                "reason": f"{type(exc).__name__}: {exc}"}


def new_worksheet(book_name: str, sheet_name: str):
    api = get_api()
    # new_sheet() returns a layer wrapper around OriginExt's Worksheets
    # collection. On current Origin builds that wrapper can expose a late-bound
    # object whose SetName method is absent. Keep page creation/name ownership
    # in the official API, then address the sheet by its verified LabTalk name.
    try:
        sheet = api.new_sheet("w", book_name)
    except Exception as exc:
        raise RuntimeError(
            f"originpro new_book failed for {book_name!r}: {type(exc).__name__}: {exc}"
        ) from exc
    if sheet is None:
        raise RuntimeError(f"originpro could not create workbook {book_name!r}.")
    sheet.name = sheet_name
    actual_book = sheet.get_book().name
    actual_sheet = sheet.name
    if api.find_sheet('w', f'[{actual_book}]{actual_sheet}') is None:
        raise RuntimeError('New worksheet could not be verified; inspect the project before retrying.')
    return actual_book, actual_sheet
def add_worksheet(book_name: str, sheet_name: str):
    api = get_api()
    book = api.find_book("w", book_name)
    if book is None:
        raise ValueError(f"originpro could not resolve workbook {book_name!r}.")
    sheet = book.add_sheet(sheet_name)
    if sheet is None:
        raise RuntimeError(f"originpro could not add sheet {sheet_name!r} to {book_name!r}.")
    resolved = api.find_sheet("w", f"[{book_name}]{sheet_name}")
    if resolved is None:
        raise RuntimeError(f"Workbook {book_name!r} may have changed but sheet {sheet_name!r} could not be verified.")
    return book.name, sheet_name


def import_csv(file_path: str, book_name: str = ""):
    api = get_api()
    book = api.new_book("w", book_name)
    if book is None:
        raise RuntimeError("originpro could not create the target worksheet.")
    sheet = book[0]
    try:
        sheet.from_file(file_path, keep_DC=False, sparks=False)
    except Exception as exc:
        raise RuntimeError(f"CSV import may have partially changed {sheet.get_book().name}; inspect the workbook before retrying. {type(exc).__name__}: {exc}") from exc
    rows, cols = sheet.shape
    if rows <= 0 or cols <= 0:
        raise RuntimeError("Origin import returned no data; inspect the workbook before retrying.")
    book_name = api.get_lt_str("page.name$")
    sheet_name = api.get_lt_str("page.active$")
    return {"name": book_name, "sheet": sheet_name,
            "rows": int(rows), "columns": int(cols)}


def write_columns(book_name: str, sheet_name: str, columns: list[list[float]],
                  names: list[str]) -> None:
    api = get_api()
    sheet = api.find_sheet("w", f"[{book_name}]{sheet_name}")
    if sheet is None:
        raise ValueError(f"originpro could not resolve worksheet [{book_name}]{sheet_name}.")
    for index, values in enumerate(columns):
        try:
            sheet.from_list(index, values)
            if index < len(names):
                sheet.set_label(index, names[index], "L")
            actual = sheet.to_list(index)
        except Exception as exc:
            raise RuntimeError(f"Writing column {index + 1} may have partially executed; inspect [{book_name}]{sheet_name} before retrying. {type(exc).__name__}: {exc}") from exc
        if len(actual) != len(values):
            raise RuntimeError(f"Column {index + 1} readback row count mismatch; inspect the worksheet.")
        for row, (expected, observed) in enumerate(zip(values, actual), start=1):
            if abs(float(expected) - float(observed)) > max(1e-12, abs(float(expected)) * 1e-12):
                raise RuntimeError(f"Column {index + 1}, row {row} readback mismatch; inspect the worksheet.")


_PLOT_TYPES = {"scatter": "s", "line": "l", "line+symbol": "y", "column": "c"}


def create_xy_graph(graph_name: str, book: str, sheet_name: str,
                    x_col: int, y_col: int, plot_type: str,
                    y_error_col: int = 0, template: str = "") -> str:
    if plot_type not in _PLOT_TYPES:
        raise ValueError(f"originpro backend does not support plot type {plot_type!r}.")
    api = get_api()
    source = api.find_sheet("w", f"[{book}]{sheet_name}")
    if source is None:
        raise ValueError(f"originpro could not resolve worksheet [{book}]{sheet_name}.")
    graph = api.new_graph(graph_name, template=template or "")
    if graph is None:
        raise RuntimeError(f"originpro could not create graph {graph_name!r}.")
    layer = graph[0]
    before = len(layer.plot_list())
    plot = layer.add_plot(source, y_col - 1, x_col - 1,
                          type=_PLOT_TYPES[plot_type],
                          colyerr=y_error_col - 1 if y_error_col else -1)
    expected = before + (2 if y_error_col else 1)
    if plot is None or len(layer.plot_list()) != expected:
        raise RuntimeError(f"originpro plot count did not match {expected} in {graph.name!r}; inspect the project before retrying.")
    layer.rescale()
    return graph.name


def add_xy_plot(graph_name: str, book: str, sheet_name: str,
                x_col: int, y_col: int, plot_type: str,
                y_error_col: int = 0) -> None:
    if plot_type not in _PLOT_TYPES:
        raise ValueError(f"originpro backend does not support plot type {plot_type!r}.")
    api = get_api()
    source = api.find_sheet("w", f"[{book}]{sheet_name}")
    graph = api.find_graph(graph_name)
    if source is None or graph is None:
        raise ValueError("originpro could not resolve the source worksheet or target graph.")
    graph.activate()
    layer = graph[0]
    before = len(layer.plot_list())
    plot = layer.add_plot(source, y_col - 1, x_col - 1,
                             type=_PLOT_TYPES[plot_type],
                             colyerr=y_error_col - 1 if y_error_col else -1)
    expected = before + (2 if y_error_col else 1)
    if plot is None or len(layer.plot_list()) != expected:
        raise RuntimeError(f"originpro plot count did not match {expected}; inspect the graph before retrying.")


def save_project(path: str = "") -> bool:
    return bool(get_api().save(path))


def export_graph(graph_name: str, path: str, fmt: str, width: int) -> str:
    graph = get_api().find_graph(graph_name)
    if graph is None:
        raise ValueError(f"originpro could not resolve graph {graph_name!r}.")
    result = graph.save_fig(path, type=fmt, replace=False,
                           width=width if fmt.lower() in {"png", "jpg", "jpeg", "tif", "tiff", "bmp"} else 0)
    if not result:
        raise RuntimeError(f"originpro export did not confirm output at {path}.")
    return result
