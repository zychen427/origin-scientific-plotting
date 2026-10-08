"""Launch the bundled Origin MCP source using the configured local Python."""
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('Origin科研绘图 requires Windows and a licensed local Origin installation.')
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from origin_pro_mcp.app import main
if __name__ == '__main__':
    main()
