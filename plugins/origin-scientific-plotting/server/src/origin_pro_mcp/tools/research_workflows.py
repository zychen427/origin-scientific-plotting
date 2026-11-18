"""Conservative inspectable research workflows built on existing Origin tools."""
import json
import math
import os
import platform
import time

from ..app import mcp
from ..missing import is_origin_missing
from ..labtalk_safe import labtalk_name, windows_path
from ..origin_connection import get_origin, graph_names, execute_labtalk, activate_window, get_lt_var, get_lt_str, get_session_identity
from .fitting import curve_fit
from .project import save_project, save_graph_template
from .style_helpers import get_plot_info
from .worksheet import get_worksheet_data


@mcp.tool()
def inspect_graph_basic(graph_name: str) -> str:
    """Inspect first-layer curve names and error-bar classification; activate the graph.

    Other layers, axes, source-column metadata, fonts and legend are not inspected.
    An empty result is inconclusive because some loaded graphs cannot enumerate plots.
    """
    name = labtalk_name(graph_name, 'graph_name')
    plots = get_plot_info(name, strict=False)
    return json.dumps({'graph': name, 'layer': 1, 'plots': plots,
                       'assessment': 'plots_found' if plots else 'no_plots_or_unreadable',
                       'not_inspected': ['other_layers', 'axes', 'source_columns', 'fonts', 'legend']}, ensure_ascii=False)


@mcp.tool()
def inspect_graph_layers(graph_name: str) -> str:
    """Enumerate a graph page's layer names and COM plot names without editing data.

    Activates the graph. A layer enumeration failure is reported as an error,
    and an unreadable plot is marked individually. Plot names are not a
    verified source-column mapping; axes, styles, and error roles are not read.
    """
    name=labtalk_name(graph_name,'graph_name')
    activate_window(name,'graph_name')
    from ..originpro_backend import is_available as _originpro_available
    if _originpro_available():
        from ..originpro_backend import get_api
        page = get_api().find_graph(name)
        if page is None:
            raise ValueError(f'Graph page {name} could not be found.')
        layers = []
        for index in range(len(page)):
            layer = page[index]
            plots = layer.plot_list()
            layers.append({'index': index + 1, 'name': layer.name,
                           'plots': [{'index': j + 1, 'name': plot.name}
                                     for j, plot in enumerate(plots)]})
        return json.dumps({'graph': name, 'layer_count': len(layers), 'layers': layers,
                           'not_inspected': ['axes', 'source_column_mapping',
                                             'error_bar_roles', 'styles', 'legend']}, ensure_ascii=False)
    pages=get_origin().GraphPages
    page=None
    for i in range(pages.Count):
        candidate=pages.Item(i)
        if candidate.Name==name:
            page=candidate;break
    if page is None:
        raise ValueError(f'Graph page {name} could not be found.')
    try:
        collection=page.Layers
        count=int(collection.Count)
    except Exception as exc:
        raise RuntimeError('Could not enumerate graph layers.') from exc
    layers=[]
    for i in range(count):
        try:
            layer=collection.Item(i)
            item={'index':i+1,'name':str(layer.Name),'plots':[]}
            try:
                plots=layer.DataPlots
                for j in range(plots.Count):
                    try: item['plots'].append({'index':j+1,'name':str(plots.Item(j).Name)})
                    except Exception as exc: item['plots'].append({'index':j+1,'error':str(exc)})
            except Exception as exc:
                item['plot_enumeration_error']=str(exc)
            layers.append(item)
        except Exception as exc:
            layers.append({'index':i+1,'error':str(exc)})
    return json.dumps({'graph':name,'layer_count':count,'layers':layers,
                       'not_inspected':['axes','source_column_mapping','error_bar_roles','styles','legend']},ensure_ascii=False)


def _process_image_path(pid: int):
    """Full image path of a PID (Windows; None elsewhere or on failure)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(4096)
            size = wintypes.DWORD(4096)
            ok = kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size))
            return buffer.value if ok else None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _file_version_info(path: str):
    """FileVersion/ProductName/FileDescription from a PE image (None on failure)."""
    try:
        import win32api
    except Exception:
        return None
    try:
        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info.get("FileVersionMS"), info.get("FileVersionLS")
        file_version = (f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
                        if ms is not None and ls is not None else None)
        strings = {}
        try:
            lang, codepage = win32api.GetFileVersionInfo(
                path, "\\VarFileInfo\\Translation")[0]
            for key in ("ProductName", "FileDescription"):
                try:
                    strings[key] = win32api.GetFileVersionInfo(
                        path,
                        f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}")
                except Exception:
                    strings[key] = None
        except Exception:
            pass
        return {"file_version": file_version,
                "product_name": strings.get("ProductName"),
                "file_description": strings.get("FileDescription")}
    except Exception:
        return None


def _origin_version_info(origin) -> dict:
    """Best-effort Origin version with an explicit source; never fabricated.

    COM builds differ: Origin <=2020 exposed ``Application.Version``; the 2026
    type library does not (its version lives on ``Application.ProjectInfo``).
    When no COM property answers, fall back to the executable image version of
    THIS session's Origin process. A null instance version with a reason is a
    correct answer — it is never filled in from another install or process.
    """
    info = {
        "instance_version": None,
        "instance_source": None,
        "instance_reason": None,
        "executable_version": None,
        "executable_path": None,
        "product_name": None,
        "file_description": None,
    }
    for attr in ("Version", "GetVersion", "VersionString"):
        try:
            value = getattr(origin, attr)
            if callable(value):
                value = value()
            if value not in (None, "") and len(str(value)) <= 200:
                info["instance_version"] = str(value)
                info["instance_source"] = f"com.Application.{attr}"
                break
        except Exception:
            continue
    if info["instance_version"] is None:
        # Some builds carry the app version on ProjectInfo(Version/OrgVersion).
        # The 2026 build reports only the PROJECT FORMAT version there (0.0),
        # which must not be passed off as the application version.
        raw = None
        try:
            project_info = getattr(origin, "ProjectInfo")
            for attr in ("Version", "OrgVersion"):
                try:
                    candidate = getattr(project_info, attr)
                    if callable(candidate):
                        candidate = candidate()
                    if candidate is not None and not isinstance(candidate, property):
                        raw = candidate
                        break
                except Exception:
                    continue
            if isinstance(raw, (int, float)) and float(raw) <= 1.0:
                info["instance_reason"] = (
                    "Origin exposes no Application.Version property; "
                    f"ProjectInfo reports the project format version ({raw!r}), "
                    "not the application version")
            elif raw not in (None, ""):
                text = str(raw)
                if len(text) <= 200:
                    info["instance_version"] = text
                    info["instance_source"] = "com.Application.ProjectInfo.Version"
            if info["instance_version"] is None and not info["instance_reason"]:
                info["instance_reason"] = (
                    "Origin exposes no readable Application.Version property")
        except Exception as exc:
            info["instance_reason"] = f"{type(exc).__name__}: {exc}"
    pid = get_session_identity().get("origin_pid")
    if pid:
        path = _process_image_path(int(pid))
        if path:
            info["executable_path"] = path
            meta = _file_version_info(path)
            if meta:
                info["executable_version"] = meta.get("file_version")
                info["product_name"] = meta.get("product_name")
                info["file_description"] = meta.get("file_description")
    return info


# Maintainer-recorded verification baselines. NOT inferred from the connected
# instance: update only together with evidence in UPGRADE-STATUS.md.
VERIFIED_ON = [
    {"origin": "2020", "build": None,
     "workflows": ["upstream tool set (historical)"],
     "date": None,
     "evidence": "upstream project history; per-skill scope documented"},
    {"origin": "2026", "build": "Origin64.exe 10.3.0.180",
     "workflows": ["worksheet+data", "line+symbol graph",
                   "publication style", "PNG export"],
     "date": "2026-11-10",
     "evidence": "DSH smoke tests; see UPGRADE-STATUS.md"},
]


@mcp.tool()
def diagnose_origin_runtime() -> str:
    """Report runtime identity: Origin version sources, daemon/build, dependencies.

    Connecting may launch an isolated Origin session. This is a connectivity
    check, not proof of rendering, compatibility or a specific GUI window.
    ``origin_version`` is the COM instance version when the build exposes one;
    it can be null on builds that do not — ``origin_executable`` then reports
    the image version and ``origin_version_reason`` explains the gap.
    """
    from importlib.metadata import version, PackageNotFoundError
    from .. import daemon as daemon_module
    from ..build_version import CODE_VERSION, IDENTITY_PROTOCOL
    packages={}
    for name in ('mcp','pywin32','Pillow','openpyxl','originpro','OriginExt'):
        try: packages[name]=version(name)
        except PackageNotFoundError: packages[name]=None
    o=get_origin()
    try:
        origin_info = _origin_version_info(o)
    except Exception as exc:
        origin_info = {"instance_version": None, "instance_source": None,
                       "instance_reason": f"{type(exc).__name__}: {exc}",
                       "executable_version": None, "executable_path": None,
                       "product_name": None, "file_description": None}
    try:
        daemon_info = daemon_module.runtime_status()
    except Exception as exc:
        daemon_info = {"active": False,
                       "reason": f"{type(exc).__name__}: {exc}"}
    try:
        orphan_report = daemon_module.candidate_orphan_origins(
            current_pids=(daemon_info.get("pool") or {}).get("origin_pids"),
            generation=daemon_info.get("generation"))
    except Exception as exc:
        orphan_report = {"error": f"{type(exc).__name__}: {exc}"}
    lockfile_hint = None
    try:
        lf = (os.environ.get("ORIGIN_PRO_MCP_LOCKFILE")
              or daemon_module.default_lockfile_path())
        data = daemon_module.read_lockfile(lf)
        # Never expose the token: discovery metadata only.
        lockfile_hint = {
            "path": lf,
            "pid": data.get("pid"),
            "code_version": data.get("code_version"),
            "identity_protocol": data.get("identity_protocol"),
            "started_at": data.get("started_at"),
            "child_pids": data.get("child_pids"),
        }
    except (OSError, ValueError):
        lockfile_hint = None
    session = get_session_identity()
    from ..originpro_backend import capability as _originpro_capability
    originpro_info = _originpro_capability()
    # Report the actual daemon session mode, not a guessed window identity.
    mode = "unknown"
    try:
        sid = session.get("session_id")
        active = daemon_module._ACTIVE_DAEMON
        if sid and active and active.pool and active.pool.get(sid) is not None:
            mode = "attached_shared" if active.pool.is_attached(sid) else "isolated"
        elif sid and os.environ.get('ORIGIN_PRO_MCP_WORKER') == '1':
            mode = "isolated"
        elif not daemon_info.get("active"):
            mode = "in_process_shared_or_unknown"
    except Exception:
        pass
    client_versions = None
    try:
        sid = session.get("session_id")
        if sid and isinstance(daemon_info.get("connected_clients"), dict):
            client_versions = daemon_info["connected_clients"].get(sid)
    except Exception:
        client_versions = None
    verified_target = session.get("verified_target")
    process_identity = session.get("origin_process")
    target_verified = (
        isinstance(verified_target, dict) and bool(verified_target.get("pid"))
    ) or (
        mode == 'isolated' and isinstance(process_identity, dict)
        and bool(process_identity.get('pid'))
        and bool(process_identity.get('creation_filetime'))
    )
    if mode == 'isolated' and target_verified:
        try:
            from ..existing_origin import _process_identity, require_window, query_peer_pid
            current = _process_identity(process_identity['pid'])
            window = require_window(process_identity['pid'])
            target_verified = (current == process_identity and
                               window['creation_filetime'] == process_identity['creation_filetime'] and
                               query_peer_pid(o) == process_identity['pid'])
        except Exception:
            target_verified = False
    return json.dumps({
        'connected': True,
        'origin_version': origin_info.get("instance_version"),
        'origin_version_source': origin_info.get("instance_source"),
        'origin_version_reason': origin_info.get("instance_reason"),
        'origin_executable': {
            'path': origin_info.get("executable_path"),
            'file_version': origin_info.get("executable_version"),
            'product_name': origin_info.get("product_name"),
            'file_description': origin_info.get("file_description"),
        },
        'code_identity': {
            'process_code_version': CODE_VERSION,
            'identity_protocol': IDENTITY_PROTOCOL,
            'daemon_code_version': daemon_info.get('code_version'),
            'connected_client_versions': client_versions,
        },
        'daemon': daemon_info,
        'lockfile_hint': lockfile_hint,
        'orphan_origin_pids': orphan_report.get("orphan_origin_pids"),
        'orphan_origin_candidates': orphan_report.get("candidates"),
        'orphan_notes': orphan_report.get("notes"),
        'verified_on': VERIFIED_ON,
        'python_version': platform.python_version(),
        'dependencies': packages,
        'originpro_backend': originpro_info,
        'session': session,
        'control_path': {'transport': 'COM',
                         'object_api': 'originpro / OriginExt' if originpro_info.get('available') else 'Origin Automation via pywin32',
                         'labtalk': 'COM Execute fallback and advanced operations',
                         'uses_physical_mouse_or_keyboard': False,
                         'mode': mode, 'target_window_verified': target_verified},
        'saved_state': 'unknown',
        'rendering_tested': False,
        'window_identity_verified': target_verified,
    }, ensure_ascii=False)


@mcp.tool()
def graph_property_snapshot(graph_name: str) -> str:
    """Read graph layers, plot names and selected axis/layout/title properties.

    The graph is activated temporarily and its previously active layer is
    restored. Unreadable values are null. This is not a complete inventory of
    every Origin object, source mapping, style property, or hidden layer.
    """
    info=json.loads(inspect_graph_layers(graph_name))
    previous=None
    try:
        previous=int(get_lt_var('page.active'))
    except Exception: pass
    numeric={'left':'layer.left','top':'layer.top','width':'layer.width','height':'layer.height',
             'x_from':'layer.x.from','x_to':'layer.x.to','x_type':'layer.x.type','x_tick_length':'layer.x.ticklength',
             'y_from':'layer.y.from','y_to':'layer.y.to','y_type':'layer.y.type','y_tick_length':'layer.y.ticklength',
             'x_tick_font_size':'layer.x.label.pt','y_tick_font_size':'layer.y.label.pt'}
    try:
        for layer in info['layers']:
            if 'error' in layer: continue
            index=layer['index']
            if not execute_labtalk(f'page.active={index};'):
                layer['properties_error']='could not activate layer';continue
            props={}
            for key,expr in numeric.items():
                try:
                    value=float(get_lt_var(expr))
                    props[key]=value if math.isfinite(value) and not is_origin_missing(value) else None
                except Exception: props[key]=None
            for key,expr in {'x_title':'xb.text$','y_title':'yl.text$','legend':'legend.text$'}.items():
                try:
                    value=get_lt_str(expr)
                    props[key]=str(value) if value is not None else None
                except Exception: props[key]=None
            layer['properties']=props
    finally:
        if previous is not None and 1<=previous<=info['layer_count']:
            execute_labtalk(f'page.active={previous};')
    info['not_inspected']=['source_column_mapping','error_bar_roles','per_plot_style','all_objects','rendered_clipping']
    return json.dumps(info,ensure_ascii=False,allow_nan=False)


@mcp.tool()
def copy_graph_style_fields(source_graph: str, target_graph: str, fields: list[str]) -> str:
    """Copy selected first-layer tick font sizes and tick lengths between graphs.

    fields may contain x_tick_font_size, y_tick_font_size, x_tick_length,
    y_tick_length. Graph data, titles and axis ranges are not intentionally
    changed. Each assigned value is read back; partial changes can remain on
    failure. Save a checkpoint before editing an existing project.
    """
    mapping={'x_tick_font_size':'layer.x.label.pt','y_tick_font_size':'layer.y.label.pt',
             'x_tick_length':'layer.x.ticklength','y_tick_length':'layer.y.ticklength'}
    if not fields or len(set(fields))!=len(fields) or any(f not in mapping for f in fields):
        raise ValueError('Select unique supported tick font size or tick length fields.')
    source=labtalk_name(source_graph,'source_graph');target=labtalk_name(target_graph,'target_graph')
    if source==target: raise ValueError('Source and target graph must differ.')
    snapshot=json.loads(graph_property_snapshot(source))
    if not snapshot['layers'] or 'properties' not in snapshot['layers'][0]:
        raise ValueError('Source first-layer properties are unavailable; no changes made.')
    values={f:snapshot['layers'][0]['properties'].get(f) for f in fields}
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 or v>1000 for v in values.values()):
        raise ValueError('A selected source style value is unavailable or invalid; no changes made.')
    inspect_graph_layers(target)
    activate_window(target,'target_graph')
    if not execute_labtalk('page.active=1;'): raise RuntimeError('Could not activate target layer; no style applied.')
    results=[]
    for field in fields:
        expr=mapping[field];value=values[field]
        if not execute_labtalk(f'{expr}={value};'):
            raise RuntimeError(f'Failed to set {field}; earlier fields may have changed.')
        try: observed=float(get_lt_var(expr))
        except Exception as exc: raise RuntimeError(f'{field} was written but readback failed; inspect target.') from exc
        results.append({'field':field,'requested':value,'observed':observed,'verified':math.isclose(observed,value,rel_tol=1e-6,abs_tol=1e-6)})
        if not results[-1]['verified']:
            raise RuntimeError(f'{field} did not match on readback; earlier fields may have changed.')
    return json.dumps({'source':source,'target':target,'layer':1,'fields':results,'visual_inspection_required':True},ensure_ascii=False)


@mcp.tool()
def graph_quality_basic(graph_name: str) -> str:
    """Check first-layer curve enumeration and explicitly report unverified attributes.

    This is a structural warning, not visual QA. An empty plot collection can
    mean either an empty graph or a read failure, especially for loaded graphs.
    """
    info=json.loads(inspect_graph_basic(graph_name))
    info['warnings']=[] if info['plots'] else ['First-layer plots are absent or could not be read.']
    info['visual_inspection_required']=True
    return json.dumps(info,ensure_ascii=False)


@mcp.tool()
def graph_quality_report(graph_name: str, image_path: str = '') -> str:
    """Check enumerated layers, basic axis properties and an optional raster export.

    Distinguishes missing/unreadable properties from detected issues. It cannot
    establish data correctness, clipping, overlap, fonts or color visibility;
    visual and scientific review remain necessary.
    """
    snapshot=json.loads(graph_property_snapshot(graph_name)); findings=[]
    if not snapshot['layers']: findings.append({'severity':'warning','detail':'No layers found or accessible.'})
    for layer in snapshot['layers']:
        idx=layer['index']; props=layer.get('properties')
        if not layer.get('plots'): findings.append({'layer':idx,'severity':'warning','detail':'No readable plots.'})
        if not props:
            findings.append({'layer':idx,'severity':'unknown','detail':'Axis properties unavailable.'});continue
        for axis in ('x','y'):
            lo=props.get(axis+'_from');hi=props.get(axis+'_to');title=props.get(axis+'_title')
            if lo is None or hi is None: findings.append({'layer':idx,'severity':'unknown','detail':f'{axis} axis limits unavailable.'})
            elif lo==hi: findings.append({'layer':idx,'severity':'warning','detail':f'{axis} axis limits are identical.'})
            if title is None: findings.append({'layer':idx,'severity':'unknown','detail':f'{axis} axis title unavailable.'})
            elif not title.strip(): findings.append({'layer':idx,'severity':'warning','detail':f'{axis} axis title is empty.'})
    image_result=None
    if image_path:
        path=windows_path(image_path,'image_path')
        if not os.path.isfile(path) or os.path.getsize(path)==0:
            findings.append({'severity':'warning','detail':'Image file missing or empty.'})
        else:
            try:
                from PIL import Image
                with Image.open(path) as im:
                    image_result={'path':path,'dimensions':list(im.size),'format':im.format,'bytes':os.path.getsize(path)}
                    im.verify()
            except Exception as exc:
                findings.append({'severity':'warning','detail':f'Image could not be verified: {exc}'})
    return json.dumps({'graph':graph_name,'findings':findings,'layers':snapshot['layers'],
                       'image':image_result,'visual_and_scientific_review_required':True,
                       'not_inspected':snapshot['not_inspected']},ensure_ascii=False,allow_nan=False)


@mcp.tool()
def merge_graphs_grid(graphs: list[str], rows: int, columns: int) -> str:
    """Merge specified graphs into a new editable grid while keeping source graphs.

    Existing source layers are copied by Origin's merge_graph X-Function.
    Shared axis and panel-label settings are not inferred. The graph list and
    layer geometry should be visually inspected; failures may leave a new page.
    """
    if len(graphs)<2 or len(graphs)>25:
        raise ValueError('Provide 2-25 distinct graphs.')
    names=[labtalk_name(n,'graph_name') for n in graphs]
    if len(set(names))!=len(names):
        raise ValueError('Graph names must be distinct.')
    if any(isinstance(x,bool) or not isinstance(x,int) or x<1 or x>25 for x in (rows,columns)) or rows*columns<len(names):
        raise ValueError('Grid dimensions must be positive, at most 25, with enough cells.')
    before=set(graph_names())
    if not set(names)<=before:
        raise ValueError('Some source graphs do not exist; merge was not attempted.')
    expression='+char(10)$+'.join('"'+n+'"' for n in names)
    cmd=f'merge_graph option:=specified graphs:={expression} row:={rows} col:={columns} keep:=1 newlayer:=0;'
    if not execute_labtalk(cmd):
        raise RuntimeError('Merge failed; inspect the project for partial output before retrying.')
    after=set(graph_names()); new=after-before
    if len(new)!=1 or not set(names)<=after:
        raise RuntimeError(f'Merge returned but graph state is ambiguous; new={sorted(new)}, missing_sources={sorted(set(names)-after)}. Inspect the project.')
    return json.dumps({'name':next(iter(new)),'source_graphs':names,'rows':rows,'columns':columns,
                       'source_graph_names_present':True,'source_content_verified':False,
                       'visual_inspection_required':True},ensure_ascii=False)


@mcp.tool()
def link_graph_axes(graph_name: str, source_layer: int, target_layers: list[int], axis: str = 'x') -> str:
    """Link selected layer axes one-to-one to a source layer on an existing graph.

    This modifies the specified graph. Axis link state is read back where the
    Origin version supports layer.axis.link. Axis units and ranges must already
    be scientifically comparable; the operation does not infer them.
    """
    name=labtalk_name(graph_name,'graph_name')
    if axis not in ('x','y'):
        raise ValueError('axis must be x or y.')
    if isinstance(source_layer,bool) or not isinstance(source_layer,int) or source_layer<1:
        raise ValueError('source_layer must be a positive integer.')
    if not target_layers or len(target_layers)>25 or len(set(target_layers))!=len(target_layers):
        raise ValueError('Provide 1-25 distinct target layers.')
    if any(isinstance(n,bool) or not isinstance(n,int) or n<1 or n==source_layer for n in target_layers):
        raise ValueError('Target layers must be positive and different from the source.')
    metadata=json.loads(inspect_graph_layers(name))
    if any(n>metadata['layer_count'] for n in [source_layer]+target_layers):
        raise ValueError('A specified layer does not exist; nothing was linked.')
    results=[]
    for n in target_layers:
        command=f'laylink igp:={name} igl:={source_layer} destlayers:={n} {axis.upper()}Axis:=1;'
        if not execute_labtalk(command):
            raise RuntimeError(f'Could not link layer {n}; earlier target layers may already be changed.')
        probe=f'range _mcp_link=[{name}]{n}!; _mcp_axis_link=_mcp_link.{axis}.link; _mcp_parent_link=_mcp_link.link;'
        state=None; parent=None
        if execute_labtalk(probe):
            try:
                value=float(get_lt_var('_mcp_axis_link'))
                if value in (0.0,1.0,3.0): state=int(value)
                parent_value=float(get_lt_var('_mcp_parent_link'))
                if parent_value.is_integer() and 0 <= parent_value <= metadata['layer_count']: parent=int(parent_value)
            except Exception: pass
        results.append({'layer':n,'axis_link_readback':state,'parent_layer_readback':parent,'verified':state==1 and parent==source_layer})
    return json.dumps({'graph':name,'source_layer':source_layer,'axis':axis,'results':results,
                       'all_verified':all(r['verified'] for r in results)},ensure_ascii=False)


@mcp.tool()
def save_new_graph_template(graph_name: str, file_path: str) -> str:
    """Save a native .otpu graph template to a new path without overwriting.

    The template is intended for new plots through create_graph(template=...),
    not selective style extraction or changes to an existing graph. Verify the
    new plot visually because different plot types may not match the template.
    """
    name=labtalk_name(graph_name,'graph_name')
    path=windows_path(file_path,'file_path')
    if not path.lower().endswith('.otpu'):
        raise ValueError('Template path must end in .otpu.')
    if os.path.exists(path):
        raise ValueError('Template path already exists; nothing was saved.')
    result=save_graph_template(name,path)
    if not os.path.isfile(path) or os.path.getsize(path)==0:
        raise RuntimeError('Template save returned but file is missing or empty.')
    return json.dumps({'source_graph':name,'path':path,'bytes':os.path.getsize(path),
                       'result':result,'visual_verification_required':True},ensure_ascii=False)


@mcp.tool()
def worksheet_slice(book_name: str, sheet_name: str, columns: list[int], start_row: int, end_row: int) -> str:
    """Return selected 1-based worksheet rows and columns.

    Origin COM GetWorksheet reads only the requested row and column ranges.
    Adjacent requested columns are transferred together; output retains the
    supplied column order.
    """
    if not columns or len(columns) > 100 or len(set(columns)) != len(columns):
        raise ValueError('Provide 1-100 unique column indices.')
    if any(isinstance(c, bool) or not isinstance(c, int) or c < 1 for c in columns):
        raise ValueError('Column indices must be positive integers.')
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (start_row, end_row)) or start_row < 1 or end_row < start_row or end_row-start_row+1 > 10000:
        raise ValueError('Rows must be a 1-based range of at most 10000 rows.')
    book=labtalk_name(book_name,'book_name'); sheet=labtalk_name(sheet_name,'sheet_name')
    target=f'[{book}]{sheet}'
    origin=get_origin(); worksheet=origin.FindWorksheet(target)
    if worksheet is None:
        raise ValueError(f'Worksheet {target} was not found.')
    if any(c > worksheet.Cols for c in columns):
        raise ValueError('A requested column is outside the worksheet.')
    if end_row > worksheet.Rows:
        raise ValueError('Requested rows exceed the worksheet.')
    groups=[]
    for col in sorted(columns):
        if groups and col==groups[-1][-1]+1: groups[-1].append(col)
        else: groups.append([col])
    by_column={}
    for group in groups:
        block=origin.GetWorksheet(target,start_row-1,group[0]-1,end_row-1,group[-1]-1)
        if not isinstance(block,(list,tuple)) or len(block)!=end_row-start_row+1:
            raise RuntimeError(f'Origin returned an unexpected block for columns {group}.')
        output=[[] for _ in group]
        for row in block:
            if not isinstance(row,(list,tuple)) or len(row)!=len(group):
                raise RuntimeError(f'Origin returned an unexpected row shape for columns {group}.')
            for i,value in enumerate(row):
                if is_origin_missing(value): value=None
                output[i].append(value)
        by_column.update(zip(group,output))
    values=[by_column[c] for c in columns]
    return json.dumps({'book':book_name,'sheet':sheet_name,'columns':columns,
                       'start_row':start_row,'end_row':end_row,
                       'data':values,'transfer':'origin_bounded'}, ensure_ascii=False)


@mcp.tool()
def batch_curve_fit(tasks: list[dict]) -> str:
    """Fit multiple specified datasets serially using the existing curve_fit tool.

    Each entry accepts curve_fit arguments, requiring data_book, data_sheet,
    x_col and y_col. Existing Origin fitting semantics apply; no automatic
    outlier exclusion, weighting or forced intercept is inferred. Fit reports
    may change the project. Per-item errors and times are returned.
    """
    required={'data_book','data_sheet','x_col','y_col'}
    allowed=required|{'function','y_error_col','plot_on_graph','x_min','x_max','peaks','peak_centers'}
    if not tasks or len(tasks)>100 or any(not isinstance(t,dict) or not required <= set(t) or set(t)-allowed for t in tasks):
        raise ValueError('Provide 1-100 valid curve_fit tasks; no fits were attempted.')
    results=[]
    for task in tasks:
        started=time.perf_counter(); item={'request':task,'ok':False}
        try:
            item['fit']=json.loads(curve_fit(**task)); item['ok']=True
        except Exception as exc:
            item['error_type']=type(exc).__name__; item['error']=str(exc); item['note']='Inspect Origin before retrying: partial fit output may exist.'
        item['seconds']=round(time.perf_counter()-started,4);results.append(item)
        if not item['ok']:
            break
    return json.dumps({'status':'partial_failure' if any(not x['ok'] for x in results) else 'success',
                       'results':results,'succeeded':sum(x['ok'] for x in results)},ensure_ascii=False)


@mcp.tool()
def save_project_checkpoint(file_path: str) -> str:
    """Save the current session project to a new .opju path; never overwrite a file.

    This is a checkpoint copy, not automatic rollback. It changes the current
    Origin project's save path as a consequence of Origin Save As.
    """
    path=windows_path(file_path,'file_path')
    if not path.lower().endswith('.opju'):
        raise ValueError('Checkpoint path must end in .opju.')
    if os.path.exists(path):
        raise ValueError('Checkpoint path already exists; nothing was saved.')
    result=save_project(path)
    if not os.path.isfile(path) or os.path.getsize(path)==0:
        raise RuntimeError('Save returned but the checkpoint is missing or empty.')
    return json.dumps({'path':path,'bytes':os.path.getsize(path),'save_result':result,
                       'note':'Current project save path changed; reopen was not verified.'},ensure_ascii=False)
