import json

from ..app import mcp
from ..origin_connection import activate_window, execute_labtalk, get_lt_var, get_lt_str
from ..labtalk_safe import (
    labtalk_name, labtalk_variable, classify_labtalk_script,
)

# Origin's numeric sentinel for a missing/unreadable property (observed on
# opposite-axis x2/y2 reads as -1.23456789e-300, P9-confirmed) is a TINY
# near-zero magnitude, not a huge negative number. The threshold sits ~18
# orders of magnitude below float64's normal minimum (~2.2e-308), i.e. deep in
# the denormal/underflow regime, so any real captured quantity (axis props,
# fit params, stats) is far larger — the only values it catches are Origin's
# sentinels. It is a magnitude heuristic (not an exact-bit-pattern match), so
# in principle a genuine sub-1e-290 result would also read as "missing"; no
# such value arises in practice. Translate it instead of leaking the raw float.
_MISSING_SENTINEL_ABS_MAX = 1e-290


def _translate_missing(value):
    try:
        if isinstance(value, (int, float)) and 0 < abs(value) < _MISSING_SENTINEL_ABS_MAX:
            return "missing"
    except TypeError:
        pass
    return value


@mcp.tool()
def run_labtalk(script: str, confirm: bool = False, capture: list[str] | None = None,
                timeout: float = 0.0, window: str = "") -> str:
    """Run a LabTalk script: escape hatch for uncovered operations.

    SAFETY: a limited list of potentially destructive tokens requires confirm=True; other file/project commands are not automatically blocked. Review every script;
    never merge `set` flags in one command (corrupts the plot); never write
    `layer.x2/.y2.majorTicks` (wipes all tick labels); `-w` vs `-erw` units
    differ; failures may be PARTIAL, never replayed; `layer.*`/`col()` hit the
    ACTIVE window; pass `window=`; `type`/`print` are unreadable: use untyped
    vars + capture. See get_skill('labtalk-gotchas').

    Args:
        script: LabTalk script; confirm: True to run it if gated.
        capture: names to read back (JSON {status,script,values}), `$` for
            strings, unreadable = "missing".
        timeout: seconds, 0 = daemon default, >0 reports a timeout while retaining
            the session; window: activate first, "" = current.
    Returns a message or refusal naming the token."""
    # Validate all capture names before activation or execution: a failed
    # capture must never follow a partially completed user script.
    safe_capture = [labtalk_variable(name, "capture") for name in (capture or [])]
    # A refused script must not even change the active Origin window.
    _ok, requires_confirm, reason = classify_labtalk_script(script)
    if requires_confirm and not confirm:
        raise ValueError(
            f"NOT EXECUTED. This script uses a gated command token ('{reason}') "
            "that can affect files, the project, or the system. Review it, then "
            "re-call run_labtalk with confirm=True to run it anyway.\n"
            f"Script: {script}"
        )
    if window:
        safe_window = labtalk_name(window, "window")
        activate_window(safe_window, "window")
    success = execute_labtalk(script)
    if not success:
        raise RuntimeError('LabTalk execution failed and may have partially modified the project; inspect the same session before retrying.')
    status = "ok" if success else "error"
    if not capture:
        msg = f"Executed {'successfully' if success else 'with errors'}: {script}"
        if not success:
            msg += "\nThe script may have partially executed; it was not retried. Inspect the project before retrying."
        return msg
    values: dict = {}
    for safe_name in safe_capture:
        if safe_name.endswith("$"):
            values[safe_name] = get_lt_str(safe_name)
        else:
            values[safe_name] = _translate_missing(get_lt_var(safe_name))
    result = {"status": status, "script": script, "values": values}
    return json.dumps(result)

@mcp.tool()
def get_labtalk_variable(name: str) -> str:
    """Read one LabTalk variable's value as a string.

    A typed declaration (`int x = 5`) is script-local and vanishes when the
    script ends; use untyped `x = 5` in run_labtalk to read it back later.

    Args:
        name: variable name; `$` suffix for strings (e.g. 'str$').
    Raises ValueError for an undefined NUMERIC variable (exist() guard); an
    undefined string variable reads back as "" - indistinguishable from empty."""
    safe_name = labtalk_variable(name, "name")
    if safe_name.endswith("$"):
        return get_lt_str(safe_name)
    if not execute_labtalk(f"_opm_lt_exist = exist({safe_name});"):
        msg = f"Could not check whether LabTalk variable '{safe_name}' exists."
        raise ValueError(msg)
    if get_lt_var("_opm_lt_exist") == 0:
        msg = (
            f"LabTalk variable '{safe_name}' is not defined. Note: a "
            "variable declared with a type (e.g. `int x = 5`) is "
            "script-local and vanishes when the script ends — use untyped "
            "assignment (`x = 5`) in run_labtalk if you want to read it "
            "back later."
        )
        raise ValueError(msg)
    return str(get_lt_var(safe_name))
