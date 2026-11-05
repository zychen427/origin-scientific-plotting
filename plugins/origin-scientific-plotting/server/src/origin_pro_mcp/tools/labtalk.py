import json

from ..app import mcp
from ..origin_connection import activate_window, execute_labtalk, get_lt_var, get_lt_str
from ..labtalk_safe import (
    labtalk_name, labtalk_variable, classify_labtalk_script, split_labtalk_statements,
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
    """Execute a LabTalk script in Origin Pro — the universal escape hatch.

    Use this for any Origin operation not covered by other tools. LabTalk is
    Origin's built-in scripting language. Most operations (data, plotting,
    styling, save, saveAs, open, expGraph, file, etc.) run freely.

    A narrow confirm gate protects a few real command tokens that can touch
    files, the project, or the system (e.g. `doc -s`/`doc -n`, `del`/`delete`,
    `win -c`/`-cd`/`-ct`, `system.`/`system(`, `run.section`/`run -*`, `dll`,
    `dde`, `getfilename`, `getsavename`, `label -r`). Keywords inside string
    literals or comments never trigger the gate. When a gated token is present
    and `confirm` is False, the script is NOT executed and a message naming the
    token is returned; re-call with `confirm=True` to run it anyway.

    Observability: LabTalk's `type`/`print` output cannot be read back over
    COM, so to inspect a computed value assign it to an (untyped) LabTalk
    variable inside `script` and name it in `capture` — e.g.
    `run_labtalk("stats col(1); mean = stats.mean;", capture=["mean"])`.
    The variables' values are read back after the script runs and returned as
    JSON. Use a `$` suffix for string variables (e.g. `capture=["name$"]`).

    A failed script may have partially executed. It is not replayed; inspect
    the current project before deciding whether a retry is safe.

    GOTCHA — active window: `layer.*`, `col()`, `%C`, and similar unqualified
    references all target the ACTIVE window, not necessarily the graph/sheet
    you mean. Pass `window=<name>` to activate that window FIRST (uses the
    same COM activation route that works on loaded graphs, unlike bare
    `win -a`), or prefer the typed tools (they take `graph_name`/`book_name`
    explicitly and never depend on window activation state).

    SAFETY-CRITICAL shortlist (Origin 2020, probe-confirmed — read
    `get_skill('labtalk-gotchas')` for the full ledger, evidence, and recipes):
      * NEVER combine multiple `-flag`s in one `set` command (e.g. `-c` +
        `-cf`) — silently corrupts the plot (color to black, or blank symbol).
      * NEVER write `layer.x2.majorTicks` / `layer.y2.majorTicks` — wipes the
        NUMBER LABELS on ALL FOUR axes, not just the opposite side.
      * `-w` (line width) units differ from error-bar `-erw`/`-erwc` (points).
      * `layer.*`/`col()` hit the ACTIVE window — use `window=` above, or a
        typed tool.
      * A raw `set`/`layer.*` command right after `create_graph`/`plotxy`
        can silently no-op for the first 1-3 calls (settle race) — prefer a
        typed tool, or expect to retry.
    Full gotcha ledger + unit/symbol tables: `get_skill('labtalk-gotchas')`.

    Args:
        script: LabTalk script to execute
        confirm: Set True to run a script that uses a gated command token
        capture: Optional list of LabTalk variable names to read back after
                 the script runs. When given, the result is a JSON object
                 {"status", "script", "values"}. A numeric value Origin can't
                 actually supply (its missing-property sentinel) is returned
                 as the string "missing" instead of a raw unreadable float.
        timeout: Optional per-call dispatch budget in seconds for this one
                 script. 0 (default) uses the daemon's configured dispatch
                 timeout. A positive value bounds this call even when the
                 global dispatch timeout is off; on overrun the daemon force-
                 resets the wedged session and returns an actionable error.
        window: Optional window name to activate before running the script —
                use this when `script` relies on the active window (`layer.*`,
                `col()`, `%C`, ...) and you are not sure it is already active.
                "" (default) runs the script against whatever is currently
                active, unchanged.

    Returns:
        Success/failure message, or an actionable not-executed message when a
        gated token is present and confirm is False. When `capture` is given,
        a JSON object with the executed status and the captured variable
        values. On failure, the script may have partially executed and is not replayed.
    """
    if window:
        safe_window = labtalk_name(window, "window")
        activate_window(safe_window, "window")
    _ok, requires_confirm, reason = classify_labtalk_script(script)
    if requires_confirm and not confirm:
        return (
            f"NOT EXECUTED. This script uses a gated command token ('{reason}') "
            "that can affect files, the project, or the system. Review it, then "
            "re-call run_labtalk with confirm=True to run it anyway.\n"
            f"Script: {script}"
        )
    success = execute_labtalk(script)
    status = "ok" if success else "error"
    if not capture:
        msg = f"Executed {'successfully' if success else 'with errors'}: {script}"
        if not success:
            msg += "\nThe script may have partially executed; it was not retried. Inspect the project before retrying."
        return msg
    values: dict = {}
    for raw_name in capture:
        safe_name = labtalk_variable(raw_name, "capture")
        if safe_name.endswith("$"):
            values[safe_name] = get_lt_str(safe_name)
        else:
            values[safe_name] = _translate_missing(get_lt_var(safe_name))
    result = {"status": status, "script": script, "values": values}
    return json.dumps(result)

@mcp.tool()
def get_labtalk_variable(name: str) -> str:
    """Get the value of a LabTalk variable.

    Gotcha: a variable declared with a type (e.g. `int x = 5`) is
    script-local — it vanishes when the script ends. Use untyped assignment
    (`x = 5`) in run_labtalk if you want to read the value back later.

    Args:
        name: Variable name. Use $ suffix for strings (e.g., 'str$')

    Returns:
        Variable value as string

    Raises:
        ValueError: if a numeric variable is not defined (checked via
            LabTalk's `exist()`, since an undefined numeric variable would
            otherwise read back as an indistinguishable 0).

    Note:
        The `exist()` guard above only applies to numeric variables. For a
        string variable ($ suffix), an undefined variable reads back as ""
        — indistinguishable from a defined-but-empty string.
    """
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
