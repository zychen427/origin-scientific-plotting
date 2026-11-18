"""Real Origin isolation and recovery checks using synthetic projects only."""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server' / 'src'))
from origin_pro_mcp.daemon import _origin_process_pids

async def main():
    output = ROOT / ('verification_worker_isolation_' + uuid.uuid4().hex[:8])
    output.mkdir()
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'calls': [],
              'origin_pids_before': sorted(_origin_process_pids()), 'status': 'running'}
    if report['origin_pids_before']:
        raise RuntimeError('Requires no running Origin processes before synthetic test')
    spec = next(iter(json.loads((ROOT/'mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
    env = os.environ.copy(); env.update(spec.get('env', {}))
    env['ORIGIN_PRO_MCP_BACKEND'] = 'originpro' if '--originpro' in sys.argv[1:] else 'com'
    env['ORIGIN_PRO_MCP_LOCKFILE'] = str(output/'daemon.json')
    sessions = []

    async def call(index, name, args=None, failure=False):
        result = await sessions[index].call_tool(name, args or {})
        value = '\n'.join(getattr(c, 'text', '') for c in result.content)
        report['calls'].append({'session': index, 'tool': name, 'args': args or {},
                                'error': result.isError, 'result': value})
        if bool(result.isError) != failure:
            raise RuntimeError(f'{index} {name}: unexpected result: {value}')
        return value

    try:
        async with AsyncExitStack() as stack:
            for _ in range(2):
                params = StdioServerParameters(command=spec['command'],
                    args=[x.replace('${PLUGIN_ROOT}', str(ROOT)) for x in spec['args']],
                    cwd=str(ROOT), env=env)
                reader, writer = await stack.enter_async_context(stdio_client(params))
                s = await stack.enter_async_context(ClientSession(reader, writer))
                await s.initialize(); sessions.append(s)
            identities, workers = [], []
            for i in range(2):
                await call(i, 'list_worksheets')
                diag = json.loads(await call(i, 'diagnose_origin_runtime'))
                assert diag['window_identity_verified'] and diag['control_path']['mode'] == 'isolated'
                identities.append(diag['session']['origin_process'])
                workers.append(diag['session']['worker_pid'])
            assert identities[0]['pid'] != identities[1]['pid']
            assert workers[0] and workers[1] and workers[0] != workers[1]
            report['identities'] = identities
            report['worker_pids'] = workers
            for i in range(2):
                name = 'Isolation' + str(i)
                await call(i, 'create_worksheet', {'book_name': name, 'sheet_name': 'Data'})
                await call(i, 'set_worksheet_data', {'book_name': name, 'sheet_name': 'Data',
                    'columns': json.dumps([[1, 2, 3], [10 + i, 20 + i, 30 + i]])})
            for i in range(2):
                data = json.loads(await call(i, 'get_worksheet_data', {'book_name': 'Isolation'+str(i), 'sheet_name': 'Data'}))
                assert data['columns'][1] == [10+i, 20+i, 30+i]
                await call(i, 'get_worksheet_data', {'book_name': 'Isolation'+str(1-i), 'sheet_name': 'Data'}, failure=True)
            await call(0, 'run_labtalk', {'script':'run.python("import time;time.sleep(6)",0);',
                                           'confirm':True, 'timeout':1}, failure=True)
            await call(0, 'list_worksheets', failure=True)
            await asyncio.sleep(7)
            await call(0, 'get_worksheet_data', {'book_name':'Isolation0', 'sheet_name':'Data'})
            await call(0, 'get_worksheet_data', {'book_name': 'Missing', 'sheet_name': 'Data'}, failure=True)
            await call(0, 'inspect_graph_layers', {'graph_name': 'Missing'}, failure=True)
            await call(0, 'save_project', {'file_path': str(output/'invalid.extension')}, failure=True)
            blocked_parent = output / 'not_a_directory'
            blocked_parent.write_text('synthetic save failure', encoding='utf-8')
            await call(0, 'save_project', {'file_path': str(blocked_parent/'cannot_save.opju')}, failure=True)
            await call(0, 'release_origin_session', failure=True)
            for i in range(2):
                await call(i, 'save_project', {'file_path': str(output / f'session{i}.opju')})
            # Hide only the verified synthetic session's window; a saved project
            # must not be closed when window ownership cannot be established.
            import win32con, win32gui
            from origin_pro_mcp.existing_origin import require_window, _process_identity
            first = identities[0]
            assert _process_identity(first['pid']) == first
            hwnd = require_window(first['pid'])['hwnd']
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            try:
                diag = json.loads(await call(0, 'diagnose_origin_runtime'))
                assert not diag['window_identity_verified']
                await call(0, 'release_origin_session', failure=True)
            finally:
                if _process_identity(first['pid']) == first:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            await asyncio.sleep(1)
            await call(0, 'release_origin_session')
            live = _origin_process_pids()
            assert identities[0]['pid'] not in live and identities[1]['pid'] in live
            await call(1, 'get_worksheet_data', {'book_name': 'Isolation1', 'sheet_name': 'Data'})
            await call(1, 'save_project', {'file_path': str(output/'session1.opju')})
            await call(1, 'release_origin_session')
            assert not _origin_process_pids()
            report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'; report['exception'] = repr(exc)
        raise
    finally:
        report['origin_pids_after'] = sorted(_origin_process_pids())
        (output/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k != 'calls'}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
