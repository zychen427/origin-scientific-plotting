"""Keep an independently created synthetic Origin open during an MCP session."""
import asyncio
import gc
import json
import os
from pathlib import Path
import sys
import uuid
import pythoncom
import win32api
import win32con
import win32event
import win32gui
import win32com.client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'/'src'))
from origin_pro_mcp.daemon import _origin_process_pids
from origin_pro_mcp.existing_origin import _process_identity, query_peer_pid, require_window

async def main():
    out=ROOT/('verification_external_origin_'+uuid.uuid4().hex[:8]);out.mkdir()
    report={'before':sorted(_origin_process_pids()),'status':'running'}
    if report['before']: raise RuntimeError('Requires cold start')
    pythoncom.CoInitialize(); external=None; handle=None
    try:
        external=win32com.client.DispatchEx('Origin.Application'); external.Visible=1
        pid=query_peer_pid(external); identity=_process_identity(pid); report['external_identity']=identity
        assert pid not in report['before']
        name=external.CreatePage(2,'Sentinel','origin')
        assert external.PutWorksheet(f'[{name}]Sheet1',[7,11,13],0,0)
        assert external.Save(str(out/'sentinel.opju')) and not bool(external.IsModified)
        spec=next(iter(json.loads((ROOT/'mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
        env=os.environ.copy();env.update(spec.get('env',{}));env['ORIGIN_PRO_MCP_LOCKFILE']=str(out/'daemon.json')
        params=StdioServerParameters(command=spec['command'],args=[x.replace('${PLUGIN_ROOT}',str(ROOT)) for x in spec['args']],cwd=str(ROOT),env=env)
        async with stdio_client(params) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                async def call(name,args=None):
                    r=await session.call_tool(name,args or {}); text='\n'.join(getattr(c,'text','') for c in r.content)
                    if r.isError: raise RuntimeError(f'{name}: {text}')
                    return text
                diag=json.loads(await call('diagnose_origin_runtime'))
                owned=diag['session']['origin_process'];report['mcp_identity']=owned
                assert diag['window_identity_verified'] and owned['pid']!=pid
                state=json.loads(await call('list_worksheets'));assert not state['workbooks']
                await call('release_origin_session')
                assert _process_identity(pid)==identity and owned['pid'] not in _origin_process_pids()
                actual=external.GetWorksheet(f'[{name}]Sheet1')
                assert [row[0] for row in actual]==[7,11,13]
                assert not bool(external.IsModified)
                report['external_project_unchanged']=True
        window=require_window(pid);assert _process_identity(pid)==identity
        handle=win32api.OpenProcess(0x00100000,False,pid)
        external=None;gc.collect();pythoncom.CoUninitialize()
        win32gui.PostMessage(window['hwnd'],win32con.WM_CLOSE,0,0)
        report['external_normal_exit']=win32event.WaitForSingleObject(handle,10000)==win32event.WAIT_OBJECT_0
        assert report['external_normal_exit'];report['status']='passed'
    except BaseException as exc:
        report['status']='failed';report['exception']=repr(exc);raise
    finally:
        if handle:handle.Close()
        report['after']=sorted(_origin_process_pids())
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
