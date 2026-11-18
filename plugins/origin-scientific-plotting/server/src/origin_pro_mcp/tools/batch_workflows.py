"""Serial batch operations using the existing checked Origin tools."""
import json
import os
import time

from ..app import mcp
from ..labtalk_safe import labtalk_name, windows_path
from .graph import create_graph, _export_via_expgraph, EXPORT_FORMATS
from .style import apply_publication_style
from .style_helpers import get_plot_info


@mcp.tool()
def batch_create_graphs(tasks: list[dict], style: dict | None = None) -> str:
    """Create graphs serially from existing Origin sheets with optional common publication style.

    Each task is a create_graph argument object: graph_name, data_book, data_sheet,
    x_col and y_col required; plot_type, y_error_col, z_col, title, template optional.
    style may contain x_label, y_label, x_min, x_max, y_min, y_max, legend_position.
    Reports actual graph names and per-item failures, including partially created graphs.
    """
    if not tasks or len(tasks) > 100:
        raise ValueError("Provide 1 to 100 graph tasks.")
    graph_keys = {"graph_name", "data_book", "data_sheet", "x_col", "y_col", "plot_type", "y_error_col", "z_col", "title", "template"}
    required = {"graph_name", "data_book", "data_sheet", "x_col", "y_col"}
    style_keys = {"x_label", "y_label", "x_min", "x_max", "y_min", "y_max", "legend_position"}
    if not isinstance(style or {}, dict) or set(style or {}) - style_keys:
        raise ValueError("Invalid common style fields.")
    for task in tasks:
        if not isinstance(task, dict) or not required <= set(task) or set(task) - graph_keys:
            raise ValueError("Each task must have required create_graph fields and no unknown fields; nothing was created.")
    results = []
    for task in tasks:
        started = time.perf_counter()
        result = {"requested_name": task["graph_name"], "ok": False, "status": "failed"}
        try:
            created = json.loads(create_graph(**task))
            result["name"] = created["name"]
            if style is not None:
                result["style_result"] = apply_publication_style(created["name"], **style)
            result["plots"] = get_plot_info(created["name"])
            if not result["plots"]:
                raise RuntimeError("No plots found after creation.")
            message = result.get("style_result", "")
            if "WARNING:" in message or "NOTE:" in message:
                result["status"] = "warning"
            else:
                result["status"] = "success"
                result["ok"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
            result["note"] = "Inspect the project before retrying; a partial graph may exist."
        result["seconds"] = round(time.perf_counter()-started, 4)
        results.append(result)
        if result['status'] == 'failed':
            break
    return json.dumps({"status": "partial_failure" if any(r['status'] == 'failed' for r in results) else "success",
                       "results": results, "succeeded": sum(r["ok"] for r in results),
                       "warnings": sum(r["status"] == "warning" for r in results)}, ensure_ascii=False)


@mcp.tool()
def batch_export_checked(graphs: list[str], output_dir: str, formats: list[str], width: int = 1200) -> str:
    """Export named graphs in multiple formats without overwriting; inspect output files.

    Raster dimensions are checked when Pillow can open the file; width is pixels,
    height follows the Origin graph aspect ratio. Each result is independent.
    """
    if not graphs or len(graphs) > 100 or not formats or len(formats) > 7:
        raise ValueError("Provide 1-100 graphs and 1-7 output formats.")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer.")
    names = [labtalk_name(n, "graph_name") for n in graphs]
    fmts = [f.lower() for f in formats]
    if any(f not in EXPORT_FORMATS for f in fmts) or len(set(fmts)) != len(fmts) or len(set(names)) != len(names):
        raise ValueError("Unknown or duplicate graph names or formats.")
    directory = windows_path(output_dir, "output_dir")
    results = []
    for name in names:
        for fmt in fmts:
            path = os.path.join(directory, f"{name}.{fmt}")
            started = time.perf_counter()
            item = {"graph": name, "format": fmt, "path": path, "ok": False}
            try:
                _export_via_expgraph(name, path, width=width, format=fmt)
                size = os.path.getsize(path)
                if size <= 0:
                    raise RuntimeError("Export is empty.")
                item["bytes"] = size
                if fmt in {"png", "jpg", "tif", "bmp"}:
                    from PIL import Image
                    with Image.open(path) as image:
                        item["dimensions"] = list(image.size)
                        image.verify()
                    if item["dimensions"][0] != width:
                        raise RuntimeError(f"Expected width {width}, got {item['dimensions'][0]}.")
                item["ok"] = True
            except Exception as exc:
                item["error_type"] = type(exc).__name__
                item["error"] = str(exc)
            item["seconds"] = round(time.perf_counter()-started, 4)
            results.append(item)
            if not item['ok']:
                break
        if results and not results[-1]['ok']:
            break
    return json.dumps({"status": "partial_failure" if any(not r['ok'] for r in results) else "success",
                       "results": results, "succeeded": sum(r["ok"] for r in results)}, ensure_ascii=False)
