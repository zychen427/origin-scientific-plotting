import os

from mcp.server.fastmcp import FastMCP

from .skills import SERVER_INSTRUCTIONS

mcp = FastMCP("origin-pro", log_level="ERROR", instructions=SERVER_INSTRUCTIONS)

# Advertise the plugin build (not the mcp SDK version) in initialize's
# serverInfo.version, so each client can tell which code is serving it.
# FastMCP does not expose a version argument; the low-level server defaults to
# the SDK version when this attribute is left unset.
try:  # pragma: no cover - private hook of an optional SDK version
    from .build_version import CODE_VERSION

    mcp._mcp_server.version = CODE_VERSION
except Exception:  # pragma: no cover
    pass

# Cutover flag: Phase 3d FLIPPED this to True — the daemon-backed shim is now the
# default entrypoint (auto-spawn + orphan self-cleanup). Force the legacy
# in-process server with ORIGIN_PRO_MCP_USE_DAEMON=0.
USE_DAEMON_DEFAULT = True


def use_daemon() -> bool:
    """Whether ``main()`` should run the daemon-backed shim instead of the
    in-process server. Reads ``ORIGIN_PRO_MCP_USE_DAEMON`` (default OFF)."""
    flag = os.environ.get("ORIGIN_PRO_MCP_USE_DAEMON")
    if flag is None:
        return USE_DAEMON_DEFAULT
    return flag.strip().lower() in ("1", "true", "yes", "on")


def main():
    """Entry point for uvx / console_scripts."""
    if use_daemon():
        from .shim import run_stdio

        run_stdio()
        return
    raise RuntimeError('In-process server mode is disabled; use the isolated worker daemon.')
