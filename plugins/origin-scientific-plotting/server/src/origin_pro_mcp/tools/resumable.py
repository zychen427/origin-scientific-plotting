"""Conservative batch graph journal: unknown outcomes are never retried automatically."""
import hashlib
import json
import os
import tempfile

from ..app import mcp
from ..labtalk_safe import windows_path, labtalk_name
from ..origin_connection import graph_names, get_remembered_project_path, get_origin
from .graph import create_graph
from .research_workflows import graph_property_snapshot


def _digest(tasks):
    raw=json.dumps(tasks,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _source_digest(task):
    book=labtalk_name(task['data_book'],'data_book')
    sheet=labtalk_name(task['data_sheet'],'data_sheet')
    values=get_origin().GetWorksheet(f'[{book}]{sheet}')
    if not isinstance(values,(list,tuple)):
        raise RuntimeError('Cannot read the source worksheet for recovery verification.')
    return _digest(values)


def _graph_digest(name):
    snapshot=json.loads(graph_property_snapshot(name))
    if (not snapshot.get('layers') or
        any('error' in layer or 'plot_enumeration_error' in layer or 'properties_error' in layer or
            any('error' in plot for plot in layer.get('plots', [])) for layer in snapshot['layers']) or
        not any(layer.get('plots') for layer in snapshot['layers'])):
        raise RuntimeError('Cannot inspect graph reliably for recovery verification.')
    return _digest(snapshot)


def _write_journal(path, data):
    directory=os.path.dirname(os.path.abspath(path))
    fd, temp=tempfile.mkstemp(prefix='.origin-journal-',suffix='.tmp',dir=directory)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(data,out,ensure_ascii=False,indent=2,allow_nan=False)
            out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def _batch_graphs_resumable_impl(tasks: list[dict], journal_path: str, resume: bool = False) -> str:
    """Create graphs serially with an on-disk journal; stop on first uncertain outcome.

    Each task contains create_graph arguments. A new run requires a new journal
    path. Resume requires the same task list and the SAME Origin project/session;
    completed graph names must still exist. A started or failed item is never
    retried automatically: inspect the project and create a fresh plan instead.
    The journal records graph creation, not project persistence; save the Origin
    project explicitly. A process crash can leave a partial graph.
    """
    required={'graph_name','data_book','data_sheet','x_col','y_col'}
    allowed=required|{'plot_type','y_error_col','z_col','title','template'}
    if not tasks or len(tasks)>100 or any(not isinstance(t,dict) or not required<=set(t) or set(t)-allowed for t in tasks):
        raise ValueError('Provide 1-100 valid graph tasks.')
    path=windows_path(journal_path,'journal_path')
    project_path=get_remembered_project_path()
    if not project_path:
        raise ValueError('Save the Origin project to a new path before creating or resuming a journal.')
    project_path=os.path.normcase(os.path.abspath(project_path))
    digest=_digest(tasks)
    if resume:
        with open(path,'r',encoding='utf-8') as fh: state=json.load(fh)
        if state.get('schema')!=1 or state.get('digest')!=digest or state.get('project_path')!=project_path or len(state.get('items',[]))!=len(tasks):
            raise ValueError('Journal does not match this task list.')
        if any(item.get('status') not in ('pending','done') for item in state['items']):
            raise RuntimeError('Journal contains an uncertain or failed item. Inspect the project before making a fresh plan.')
        existing=set(graph_names())
        if any(item.get('name') not in existing for item in state['items'] if item['status']=='done'):
            raise RuntimeError('A completed graph is absent. Open the original project or inspect before retrying.')
        for i,item in enumerate(state['items']):
            if item['status']=='done' and (item.get('source_digest') != _source_digest(tasks[i]) or item.get('graph_digest') != _graph_digest(item['name'])):
                raise RuntimeError(f'Completed graph or source data changed for item {i+1}; inspect before continuing.')
    else:
        state={'schema':1,'digest':digest,'project_path':project_path,'items':[{'index':i,'status':'pending'} for i in range(len(tasks))]}
        try:
            with open(path,'x',encoding='utf-8') as out:
                json.dump(state,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        except FileExistsError:
            raise ValueError('Journal already exists; pass resume=True after checking the project.')
    for i,task in enumerate(tasks):
        item=state['items'][i]
        if item['status']=='done': continue
        item['status']='started';_write_journal(path,state)
        try:
            source_digest=_source_digest(task)
            result=json.loads(create_graph(**task))
            name=result['name']
            if name not in graph_names(): raise RuntimeError('Created graph could not be found.')
            item.update(status='done',name=name,source_digest=source_digest,graph_digest=_graph_digest(name))
        except Exception as exc:
            item.update(status='uncertain',error=str(exc));_write_journal(path,state)
            return json.dumps({'status':'stopped','journal':path,'items':state['items'],
                               'note':'Inspect the project; do not automatically retry this item.'},ensure_ascii=False)
        _write_journal(path,state)
    return json.dumps({'status':'complete','journal':path,'items':state['items'],
                       'note':'Save the Origin project separately.'},ensure_ascii=False)


@mcp.tool()
def batch_graphs_resumable(tasks: list[dict], journal_path: str, resume: bool = False) -> str:
    """Create graphs serially with a journal and refuse concurrent journal use.

    The project must be saved first. Resume requires the original project path,
    the same tasks and existing completed graph names. A started or failed item
    is never retried automatically. Save the project separately. If a process
    crashes, its .lock file requires manual inspection and removal before retry.
    """
    path=windows_path(journal_path,'journal_path')
    lock=path+'.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise RuntimeError('Journal is locked or a prior run stopped unexpectedly; inspect it before retrying.')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(f'pid={os.getpid()}\n')
        return _batch_graphs_resumable_impl(tasks,path,resume)
    finally:
        os.unlink(lock)
