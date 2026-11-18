"""Launch the bundled Origin MCP source using the configured local Python."""
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('Origin科研绘图 requires Windows and a licensed local Origin installation.')

# The daemon discovery lockfile is resolved in ONE place (origin_pro_mcp.shim
# `resolve_lockfile_path`): explicit argument > non-empty ORIGIN_PRO_MCP_LOCKFILE
# > the unified default in origin_pro_mcp.daemon. A private default here used to
# silently disagree with the shim/daemon, so it is intentionally not set.

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from origin_pro_mcp.app import main
if __name__ == '__main__':
    main()
