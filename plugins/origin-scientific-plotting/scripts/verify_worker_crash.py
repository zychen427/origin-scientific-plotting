"""Controlled worker crash on one saved synthetic project; never kills Origin."""
import asyncio
import gc
import json
import os
from pathlib import Path
import sys
import uuid
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server' / 'src'))
from origin_pro_mcp.daemon import _origin_process_pids
from origin_pro_mcp.existing_origin import _process_identity, query_peer_pid

async def main():
    import win32api, win32event
    out = ROOT / ('verification_worker_crash_' + uuid.uuid4().hex[:8]); out.mkdir()
    report = {'before': sorted(_origin_process_pids()), 'status': 'running', 'calls': []}
    if report['before']:
        raise RuntimeError('Requires a cold start')
    spec = next(iter(json.loads((ROOT/'mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
    env = os.environ.copy(); env.update(spec.get('env', {})); env['ORIGIN_PRO_MCP_LOCKFILE'] = str(out/'daemon.json')
    env['ORIGIN_PRO_MCP_BACKEND'] = 'originpro'
    params = StdioServerParameters(command=spec['command'],
        args=[x.replace('${PLUGIN_ROOT}', str(ROOT)) for x in spec['args']], cwd=str(ROOT), env=env)
    async def call(s, name, args=None):
        result = await s.call_tool(name, args or {})
        text = '\n'.join(getattr(c, 'text', '') for c in result.content)
        report['calls'].append({'tool': name, 'error': result.isError, 'result': text})
        return result.isError, text
    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as s:
                await s.initialize()
                err, text = await call(s, 'diagnose_origin_runtime'); assert not err
                diag = json.loads(text); session = diag['session']; origin = session['origin_process']
                worker = _process_identity(session['worker_pid'])
                assert Path(worker['image']).name.lower() in ('python.exe', 'pythonw.exe')
                assert worker['pid'] != os.getpid() and origin['pid'] not in report['before']
                report['origin'] = origin; report['worker'] = worker
                err, text = await call(s, 'create_worksheet', {'book_name':'CrashProbe','sheet_name':'Data'}); assert not err
                book = json.loads(text)
                err, _ = await call(s, 'set_worksheet_data', {'book_name':book['name'], 'sheet_name':book['sheet'], 'columns':'[[1,2],[3,4]]'}); assert not err
                err, _ = await call(s, 'save_project', {'file_path':str(out/'saved.opju')}); assert not err
                assert _process_identity(worker['pid']) == worker
                h = win32api.OpenProcess(0x0001 | 0x00100000 | 0x1000, False, worker['pid'])
                try:
                    assert _process_identity(worker['pid']) == worker
                    win32api.TerminateProcess(h, 7)
                    assert win32event.WaitForSingleObject(h, 10000) == win32event.WAIT_OBJECT_0
                finally: h.Close()
                await asyncio.sleep(1)
                err, text = await call(s, 'list_worksheets'); assert err and ('worker' in text.lower())
                assert _process_identity(origin['pid']) == origin
                assert _origin_process_pids() == {origin['pid']}
                report['worker_replacement_refused'] = True
                # Recovery of this saved synthetic Origin is explicitly tied to
                # its original PID/image/creation identity; no other Origin exists.
                import pythoncom, win32com.client
                pythoncom.CoInitialize()
                app = win32com.client.Dispatch('Origin.ApplicationSI')
                assert query_peer_pid(app) == origin['pid'] and _process_identity(origin['pid']) == origin
                assert not bool(app.IsModified)
                handle = win32api.OpenProcess(0x00100000, False, origin['pid'])
                try:
                    app.CanClose = True; app.Exit(); app = None; gc.collect(); pythoncom.CoUninitialize()
                    report['origin_exited'] = win32event.WaitForSingleObject(handle, 10000) == win32event.WAIT_OBJECT_0
                finally: handle.Close()
                assert report['origin_exited']
                report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'; report['exception'] = repr(exc)
        raise
    finally:
        report['after'] = sorted(_origin_process_pids())
        (out/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k != 'calls'}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
