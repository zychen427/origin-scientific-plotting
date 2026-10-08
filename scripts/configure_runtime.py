"""Configure a cloned plugin to use an existing Windows Python environment."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Check the interpreter without modifying configuration.')
    args = parser.parse_args()
    executable = args.python.expanduser().resolve()
    if not executable.is_file():
        raise SystemExit('Python executable not found: ' + str(executable))
    probe = '''import sys,json,importlib.metadata as m
import mcp.server.fastmcp,win32com.client,PIL
print(json.dumps({'platform':sys.platform,'python':list(sys.version_info[:3]),'dependencies':{k:m.version(k) for k in ['mcp','pywin32','Pillow']}}))'''
    result = subprocess.run([str(executable), '-c', probe], text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise SystemExit('Required environment check failed. Install server/requirements.txt in the selected environment.\n' + result.stderr)
    info = json.loads(result.stdout)
    if info['platform'] != 'win32' or tuple(info['python']) < (3, 10):
        raise SystemExit('A Windows Python >=3.10 is required.')
    if not info['dependencies']['mcp'].startswith('1.'):
        raise SystemExit('This source requires MCP 1.x; install the bundled requirements.')
    if not args.check:
        config = ROOT / 'plugins/origin-scientific-plotting/mcp.json'
        data = json.loads(config.read_text(encoding='utf-8'))
        backup = ROOT / '.local-config'
        backup.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copy2(config, backup / ('mcp.before.' + stamp + '.json'))
        data['mcpServers']['origin-scientific-plotting']['command'] = str(executable)
        config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        info['configured'] = str(config)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
