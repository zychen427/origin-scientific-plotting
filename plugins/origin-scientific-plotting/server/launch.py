"""Launch the bundled Origin MCP source using the configured local Python."""
import os
import sys
import tempfile
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('Origin科研绘图 requires Windows and a licensed local Origin installation.')
# Keep this maintained plugin separate from upstream or older daemon versions.
# Explicit caller configuration still wins.
os.environ.setdefault('ORIGIN_PRO_MCP_LOCKFILE', str(Path(
    os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
) / 'origin-pro-mcp-research-021' / 'daemon.json'))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from origin_pro_mcp.app import main
if __name__ == '__main__':
    main()
