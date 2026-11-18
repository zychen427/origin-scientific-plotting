import threading
import time

from .labtalk_safe import labtalk_name

# Per-thread COM proxy store. Each thread (e.g. a daemon session worker) holds
# its own Origin instance, so the cached proxy never leaks across threads.
_state = threading.local()
_MAINWND_SHOW = 1

def _connection_alive(origin) -> bool:
    """Ping the cached COM proxy — stale proxies raise after Origin closes.

    Retries once on a transient error so a momentarily-busy (but still alive)
    Origin isn't mistaken for dead — a false negative would spawn a redundant
    instance and orphan the live one."""
    for attempt in range(2):
        try:
            origin.Visible
            return True
        except AttributeError:
            return True  # non-COM stand-in (tests) without a Visible property
        except Exception:
            if attempt == 0:
                time.sleep(0.25)
                continue
            return False
    return False


def _close_instance(inst) -> None:
    """Best-effort close of an Origin instance (COM). Used before relaunching a
    dead/stale proxy so a still-alive process isn't left orphaned."""
    for closer in ("Exit", "Close"):
        fn = getattr(inst, closer, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            break


def set_session_origin(origin, factory=None, session_id=None, verified_target=None) -> None:
    """Bind a COM proxy to the current thread (daemon worker / test injection).

    ``factory`` (daemon sessions) is the zero-arg callable that launched this
    session's OWN isolated instance. An unresponsive existing proxy is reported
    without replacing or closing its Origin. The factory is used only when no
    proxy is bound, never as a fallback to a shared ApplicationSI server.

    ``session_id`` (daemon sessions) is stashed thread-locally so
    project-path changes on this worker can be reported to the daemon's session
    ledger without origin_connection importing the daemon (avoids a cycle).
    """
    _state.origin = origin
    _state.created_graphs = set()
    if factory is None and hasattr(_state, 'origin_pid'):
        # A reconnect may create a different process; never report stale PID.
        _state.origin_pid = None
    if factory is not None:
        _state.factory = factory
    if session_id is not None:
        _state.session_id = session_id
    if verified_target is not None:
        _state.verified_target = dict(verified_target)


def clear_session_origin() -> None:
    """Drop the current thread's proxy and factory (full session teardown)."""
    for attr in ("origin", "factory", "project_path", "session_id", "origin_pid", "origin_process", "verified_target", "created_graphs"):
        if hasattr(_state, attr):
            delattr(_state, attr)


# --------------------------------------------------------------------------- #
# Session-ledger seam (registered by the daemon; None in in-process mode)      #
# --------------------------------------------------------------------------- #
# The daemon registers callbacks here so project-path changes and load-time
# collision checks can consult its ledger WITHOUT origin_connection importing
# daemon (which would be a cycle). Both are no-ops until registered.
_session_context_writer = None
_session_collision_reader = None


def set_session_context_writer(fn) -> None:
    """Register (or clear with ``None``) the ledger writer the daemon uses to
    record this thread's session -> project-path changes."""
    global _session_context_writer
    _session_context_writer = fn


def set_session_collision_reader(fn) -> None:
    """Register (or clear with ``None``) the ledger reader load_project uses to
    detect another live Origin holding the same project."""
    global _session_collision_reader
    _session_collision_reader = fn


def _notify_session_context(path) -> None:
    """Report this thread's (session_id, path) to the ledger writer if wired."""
    fn = _session_context_writer
    sid = getattr(_state, "session_id", None)
    if fn is None or sid is None:
        return
    try:
        fn(sid, path)
    except Exception:
        pass


def check_project_collision(path):
    """Ask the ledger whether another live Origin holds ``path`` (or None)."""
    fn = _session_collision_reader
    sid = getattr(_state, "session_id", None)
    if fn is None or sid is None:
        return None
    try:
        return fn(sid, path)
    except Exception:
        return None


def remember_project_path(path) -> None:
    """Record the last project this thread loaded/saved, so a relaunch after a
    crash (dead COM proxy) can auto-reopen it. Falsy value forgets it (e.g.
    after ``new_project``). Also reports the change to the session ledger."""
    if path:
        _state.project_path = path
    elif hasattr(_state, "project_path"):
        del _state.project_path
    _notify_session_context(path if path else None)


def get_remembered_project_path():
    return getattr(_state, "project_path", None)


def get_session_identity():
    """Return only thread-local session metadata; no process is opened or closed."""
    import os
    target = getattr(_state, 'verified_target', None)
    return {'session_id': getattr(_state, 'session_id', None),
            'worker_pid': os.getpid() if os.environ.get('ORIGIN_PRO_MCP_WORKER') == '1' else None,
            'remembered_project_path': getattr(_state, 'project_path', None),
            'origin_pid': getattr(_state, 'origin_pid', None) or (target or {}).get('pid'),
            'origin_process': getattr(_state, 'origin_process', None) or target,
            'verified_target': target}


def remember_created_graph(name: str) -> None:
    """Mark a graph created by this session for guarded LabTalk fallbacks."""
    graphs = set(getattr(_state, "created_graphs", set()))
    graphs.add(str(name))
    _state.created_graphs = graphs


def is_session_created_graph(name: str) -> bool:
    """Whether ``name`` is a graph created by this live Origin session."""
    return str(name) in getattr(_state, "created_graphs", set())


def forget_created_graphs() -> None:
    """Invalidate graph provenance when the current project is replaced."""
    _state.created_graphs = set()


def set_session_pid(pid):
    _state.origin_pid = pid
    _state.origin_process = None
    if pid:
        try:
            from .existing_origin import _process_identity
            _state.origin_process = _process_identity(int(pid))
        except Exception:
            pass


def _reopen_remembered_project(origin) -> None:
    """Best-effort: reopen the remembered on-disk project into a freshly
    relaunched instance. A crash/close still drops unsaved edits, but the last
    saved project comes back instead of an empty session. Fully guarded."""
    import os

    path = getattr(_state, "project_path", None)
    if not path or not os.path.isfile(path):
        return
    try:
        origin.Load(path)
    except Exception:
        pass


def explain_com_error(exc):
    """Return a diagnostic without assuming access errors mean bad registration."""
    code = getattr(exc, "hresult", None)
    if code is not None:
        code = int(code) & 0xffffffff
    if code == 0x80070005:
        return ("Origin COM access denied (0x80070005). Check whether this "
                "process runs inside a restricted sandbox or under a different "
                "Windows account/session. Test using the normal MCP host or an "
                "appropriately permitted desktop process; do not modify COM "
                "registration solely because access was denied.")
    if code == 0x80040154:
        return ("Origin COM class not registered (0x80040154). Check the "
                "Origin automation registration and the client architecture.")
    suffix = f" (HRESULT 0x{code:08X})" if code is not None else ""
    return f"Origin COM connection failed{suffix}: {exc}"


def get_origin():
    origin = getattr(_state, "origin", None)
    if origin is not None and not _connection_alive(origin):
        # A COM ping can fail while Origin is busy or showing a dialog. Never
        # close or replace an instance on an ambiguous liveness failure: it may
        # contain the user's unsaved work. Let the operator inspect and retry.
        raise RuntimeError(
            "The existing Origin connection is not responding. No window was "
            "closed or replaced. Check Origin for a dialog or busy operation, "
            "then retry after inspecting the current project."
        )
    if origin is None:
        raise RuntimeError(
            "No Origin instance is bound to this session. Refusing implicit "
            "attachment or replacement; inspect the session and start a new "
            "explicitly isolated session if needed."
        )
    return origin

def execute_labtalk(script: str) -> bool:
    o = get_origin()
    return o.Execute(script)

def get_lt_var(name: str) -> float:
    return get_origin().LTVar(name)

def get_lt_str(name: str) -> str:
    return get_origin().LTStr(name)

# ASCII record separator — cannot appear in an Origin window/sheet name, so it
# is a safe delimiter for the LabTalk-built name list.
_ENUM_DELIM = "\x1e"


def safe_page_names(pages) -> list:
    """Top-level names of a COM page collection, isolating a bad/corrupt entry
    so one unreadable window can't abort the whole enumeration (which, on a
    heavy project, is what can wedge/crash the COM bridge)."""
    names: list = []
    try:
        count = pages.Count
    except Exception:
        return names
    for i in range(count):
        try:
            names.append(pages.Item(i).Name)
        except Exception:
            continue
    return names


def sheet_names(book_name: str) -> list:
    """Sheet (layer) names of a workbook via LabTalk's internal ``layer$(k)``
    loop — never the deep ``page.Layers.Item(j).Name`` COM traversal, which
    instantiates a proxy per sheet and can HARD-CRASH Origin on heavy projects.
    Crash-safe (verified on Origin 2020). Returns [] on any failure."""
    o = get_origin()
    try:
        o.Execute(
            f'string _opm_sh$="";win -a {book_name};'
            f'for(int _opmk=1;_opmk<=page.nlayers;_opmk++)'
            f'{{_opm_sh$=_opm_sh$+layer$(_opmk).name$+"{_ENUM_DELIM}";}}'
        )
        raw = o.LTStr("_opm_sh$") or ""
        return [s for s in raw.split(_ENUM_DELIM) if s]
    except Exception:
        return []


def workbook_names() -> list:
    """Names of all open workbooks (per-item isolated)."""
    return safe_page_names(get_origin().WorksheetPages)


def graph_names() -> list:
    """Names of all open graph windows (per-item isolated)."""
    return safe_page_names(get_origin().GraphPages)


def matrix_names() -> list:
    """Names of all open matrix books (per-item isolated)."""
    return safe_page_names(get_origin().MatrixPages)

def require_matrix(book: str, sheet: str = "MSheet1") -> str:
    """Return the [book]sheet matrix reference, or raise with open matrices."""
    target = f"[{book}]{sheet}"
    if get_origin().FindMatrixSheet(target) is None:
        mats = ", ".join(matrix_names()) or "(none)"
        msg = f"Matrix {target} not found. Open matrices: {mats}."
        raise ValueError(msg)
    return target

def require_worksheet(book: str, sheet: str) -> str:
    """Return the [book]sheet reference, or raise with the open workbooks."""
    target = f"[{book}]{sheet}"
    if get_origin().FindWorksheet(target) is None:
        books = ", ".join(workbook_names()) or "(none)"
        msg = f"Worksheet {target} not found. Open workbooks: {books}."
        raise ValueError(msg)
    return target

def require_graph(graph_name: str):
    """Return the graph's Layer1, or raise with the list of open graphs."""
    layer = get_origin().FindGraphLayer(f"[{graph_name}]Layer1")
    if layer is None:
        graphs = ", ".join(graph_names()) or "(none)"
        msg = f"Graph '{graph_name}' not found. Open graphs: {graphs}."
        raise ValueError(msg)
    return layer

def activate_window(name: str, field: str = "window") -> None:
    """Activate a window by name, or raise with the list of open windows.

    Origin's `win -a` silently returns False for unknown windows, and any
    follow-up command would then hit whatever window happens to be active —
    so every tool must go through this guard before window-scoped commands.
    """
    safe_name = labtalk_name(name, field)
    # A newly plotted graph is commonly already active. Skip the redundant
    # `win -a` call on an exact page-name match; Origin 2026 can reject that
    # call while finishing the first graph command.
    try:
        if get_lt_str("page.name$") == safe_name:
            return
    except Exception:
        pass
    if not execute_labtalk(f"win -a {safe_name};"):
        books = ", ".join(workbook_names()) or "(none)"
        graphs = ", ".join(graph_names()) or "(none)"
        msg = (
            f"Window '{safe_name}' not found. "
            f"Open workbooks: {books}. Open graphs: {graphs}."
        )
        raise ValueError(msg)
