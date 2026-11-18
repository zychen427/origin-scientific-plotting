"""Test installed Origin MCP with two independent synthetic complex plots."""
import asyncio
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(os.environ.get('ORIGIN_TEST_ROOT', Path(__file__).resolve().parents[1])).resolve()
OUT = Path(os.environ.get('ORIGIN_TEST_OUTPUT', ROOT.parent / 'verification')).resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'server/src'))
from origin_pro_mcp.daemon import _origin_process_pids

async def main():
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'installed_root': str(ROOT),
              'origin_before': sorted(_origin_process_pids()), 'cases': []}
    spec = next(iter(json.loads((ROOT/'mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
    env = os.environ.copy(); env.update(spec.get('env', {})); env['ORIGIN_PRO_MCP_LOCKFILE'] = str(OUT/'daemon.json')
    async def run_case(kind):
        item = {'case': kind, 'calls': [], 'status': 'running'}
        report['cases'].append(item)
        params = StdioServerParameters(command=spec['command'],
            args=[v.replace('${PLUGIN_ROOT}',str(ROOT)) for v in spec['args']],cwd=str(ROOT),env=env)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                initialized=await session.initialize();item['server_version']=initialized.serverInfo.version
                expected=os.environ.get('ORIGIN_TEST_VERSION','0.5.1')
                assert item['server_version'].startswith(expected+'+')
                async def call(name, data=None):
                    response=await session.call_tool(name,data or {})
                    txt='\n'.join(getattr(x,'text','') for x in response.content)
                    item['calls'].append({'name':name,'args':data or {},'error':response.isError,'result':txt})
                    if response.isError: raise RuntimeError(f'{name}: {txt}')
                    return txt
                def parse(txt): return json.JSONDecoder().raw_decode(txt.lstrip())[0]
                try:
                    await call('list_skills'); await call('get_skill',{'name':'plot-preflight'})
                    diag=parse(await call('diagnose_origin_runtime'))
                    assert diag['control_path']['mode']=='isolated' and diag['window_identity_verified']
                    item['identity']=diag['session']; item['backend']=diag['originpro_backend']
                    assert item['backend']['available']
                    if kind=='multi_curve_errorbars':
                        book=parse(await call('create_worksheet',{'book_name':'ComplexErr','sheet_name':'Data'}))
                        x=list(range(1,9)); y1=[2+1.2*v for v in x]; e1=[0.15+0.02*v for v in x]
                        y2=[2.5+0.75*v for v in x]; e2=[0.12+0.015*v for v in x]
                        cols=[x,y1,e1,y2,e2]
                        await call('set_worksheet_data',{'book_name':book['name'],'sheet_name':book['sheet'],
                                   'columns':json.dumps(cols),'column_names':'Time,CurveA,ErrA,CurveB,ErrB'})
                        data=parse(await call('get_worksheet_data',{'book_name':book['name'],'sheet_name':book['sheet']}))
                        assert all(len(a)==len(b) and all(abs(v-u)<1e-10 for v,u in zip(a,b)) for a,b in zip(data['columns'][:5],cols))
                        graph=parse(await call('create_graph',{'graph_name':'ComplexErrorGraph','data_book':book['name'],
                            'data_sheet':book['sheet'],'x_col':1,'y_col':2,'y_error_col':3,'plot_type':'line+symbol'}))
                        await call('add_plot_to_graph',{'graph_name':graph['name'],'data_book':book['name'],
                            'data_sheet':book['sheet'],'x_col':1,'y_col':4,'y_error_col':5,'plot_type':'line+symbol'})
                        layers=parse(await call('inspect_graph_layers',{'graph_name':graph['name']}))
                        item['layers_before']=layers
                        assert layers['layer_count']==1 and len(layers['layers'][0]['plots'])==4
                        roles=parse(await call('inspect_graph_basic',{'graph_name':graph['name']}))['plots']
                        assert [p['is_error'] for p in roles]==[False,True,False,True]
                        item['plot_roles_before']=roles
                        await call('set_plot_style',{'graph_name':graph['name'],'plot_index':1,'line_width':2.0,'symbol_size':7,'error_bar_width':1.2})
                        await call('apply_publication_style',{'graph_name':graph['name'],'x_label':'Time (h)','y_label':'Response (a.u.)'})
                    else:
                        grid=[[round(math.sin(i/2)+math.cos(j/3)+i*j/40,8) for j in range(9)] for i in range(7)]
                        grid[2][4]=None
                        matrix=parse(await call('create_matrix',{'book_name':'ComplexMatrix','rows':7,'cols':9}))
                        await call('set_matrix_data',{'book_name':matrix['name'],'data':json.dumps(grid)})
                        read=parse(await call('get_matrix_data',{'book_name':matrix['name']}))['rows']
                        assert len(read)==7 and all(len(row)==9 for row in read)
                        for row_a,row_b in zip(grid,read):
                            for a,b in zip(row_a,row_b):
                                assert (a is None and b is None) or (a is not None and b is not None and abs(a-b)<1e-7)
                        graph=parse(await call('create_matrix_plot',{'matrix_book':matrix['name'],'plot_type':'contour','graph_name':'ComplexContour','z_label':'Synthetic response'}))
                        layers=parse(await call('inspect_graph_layers',{'graph_name':graph['name']}))
                        item['layers_before']=layers
                        assert layers['layer_count']>=1 and layers['layers'][0]['plots']
                    item['graph']=graph['name']
                    png=OUT/(kind+'.png'); project=OUT/(kind+'.opju')
                    await call('export_graph',{'graph_name':graph['name'],'file_path':str(png),'format':'png','width':1400})
                    await call('save_project',{'file_path':str(project)})
                    await call('load_project',{'file_path':str(project),'replace_current':True})
                    reopened=parse(await call('inspect_graph_layers',{'graph_name':graph['name']}))
                    assert reopened['layer_count'] == item['layers_before']['layer_count']
                    assert len(reopened['layers'][0]['plots']) == len(item['layers_before']['layers'][0]['plots'])
                    item['layers_reopened']=reopened
                    if kind=='multi_curve_errorbars':
                        roles=parse(await call('inspect_graph_basic',{'graph_name':graph['name']}))['plots']
                        assert [p['is_error'] for p in roles]==[False,True,False,True]
                        item['plot_roles_reopened']=roles
                        data2=parse(await call('get_worksheet_data',{'book_name':book['name'],'sheet_name':book['sheet']}))
                        assert all(len(a)==len(b) and all(abs(v-u)<1e-10 for v,u in zip(a,b)) for a,b in zip(data2['columns'][:5],cols))
                    else:
                        data2=parse(await call('get_matrix_data',{'book_name':matrix['name']}))['rows']
                        assert data2==read
                    await call('save_project',{'file_path':str(project)})
                    item['png']=str(png);item['project']=str(project);item['status']='passed'
                except Exception as exc:
                    item['status']='failed';item['error']=f'{type(exc).__name__}: {exc}'
                finally:
                    # Save this explicitly synthetic session before attempting release.
                    if item.get('identity'):
                        try:
                            recovery=OUT/(kind+'_checkpoint.opju')
                            saved=await session.call_tool('save_project',{'file_path':str(recovery)})
                            item['recovery_save']={'error':saved.isError,'result':str(saved.content)}
                            if not saved.isError:
                                rel=await session.call_tool('release_origin_session',{})
                                item['release']={'error':rel.isError,'result':str(rel.content)}
                        except Exception as exc: item['cleanup_error']=f'{type(exc).__name__}: {exc}'
    try:
        for case in ('multi_curve_errorbars','matrix_contour'):
            await run_case(case)
    except Exception as exc:
        report['fatal']=f'{type(exc).__name__}: {exc}'
    finally:
        report['origin_after']=sorted(_origin_process_pids())
        report['status']='passed' if len(report['cases'])==2 and all(c['status']=='passed' and not c.get('release',{}).get('error',True) for c in report['cases']) else 'failed'
        (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='cases'}|{'cases':[{'case':c['case'],'status':c['status'],'error':c.get('error'),'release':c.get('release')} for c in report['cases']]},ensure_ascii=False,indent=2))

if __name__=='__main__': asyncio.run(main())
