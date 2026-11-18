"""Explicit JSON workflow plans; no executable code or implicit scientific choices."""
import json
import os
from ..app import mcp
from ..labtalk_safe import windows_path
from .batch_workflows import batch_create_graphs


def _validate(plan):
    if not isinstance(plan,dict) or set(plan)!={'schema','description','tasks','style'} or plan['schema']!=1:
        raise ValueError('Invalid workflow template schema.')
    if not isinstance(plan['description'],str) or len(plan['description'])>500:
        raise ValueError('description must be text of at most 500 characters.')
    tasks=plan['tasks'];style=plan['style']
    required={'graph_name','data_book','data_sheet','x_col','y_col'}
    allowed=required|{'plot_type','y_error_col','z_col','title','template'}
    if not isinstance(tasks,list) or not tasks or len(tasks)>100 or any(not isinstance(t,dict) or not required<=set(t) or set(t)-allowed for t in tasks):
        raise ValueError('Invalid graph tasks.')
    if style is not None and (not isinstance(style,dict) or set(style)-{'x_label','y_label','x_min','x_max','y_min','y_max','legend_position'}):
        raise ValueError('Invalid common style.')
    json.dumps(plan,allow_nan=False)
    return plan


@mcp.tool()
def save_workflow_template(file_path: str, description: str, tasks: list[dict], style: dict | None = None) -> str:
    """Save explicit batch graph source mappings and style to a new JSON template.

    No data are copied, normalized, or interpreted. A template references the
    named Origin workbooks/sheets and should be checked before every execution.
    """
    path=windows_path(file_path,'file_path')
    if not path.lower().endswith('.json'): raise ValueError('Template path must end in .json.')
    plan=_validate({'schema':1,'description':description,'tasks':tasks,'style':style})
    try:
        with open(path,'x',encoding='utf-8') as out:
            json.dump(plan,out,ensure_ascii=False,indent=2,allow_nan=False)
    except FileExistsError:
        raise ValueError('Template exists; it was not overwritten.')
    return json.dumps({'path':path,'task_count':len(tasks),'status':'saved'},ensure_ascii=False)


@mcp.tool()
def read_workflow_template(file_path: str) -> str:
    """Read and validate a JSON workflow plan; does not connect to Origin."""
    path=windows_path(file_path,'file_path')
    if not os.path.isfile(path) or os.path.getsize(path)>1000000:
        raise ValueError('Template is missing or exceeds the 1 MB limit.')
    with open(path,encoding='utf-8') as inp: plan=_validate(json.load(inp))
    return json.dumps({'path':path,'plan':plan},ensure_ascii=False,allow_nan=False)


@mcp.tool()
def run_workflow_template(file_path: str) -> str:
    """Run a previously inspected JSON template against named current Origin sheets.

    This creates graphs and can partially succeed. Units, data provenance and
    mappings must be checked before calling. Existing plotting safeguards apply.
    """
    plan=json.loads(read_workflow_template(file_path))['plan']
    result=json.loads(batch_create_graphs(plan['tasks'],plan['style']))
    return json.dumps({'template':file_path,'result':result},ensure_ascii=False,allow_nan=False)
