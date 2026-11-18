"""Explicit, traceable preprocessing for selected mass spectra."""
import json
import math
import uuid

from ..app import mcp
from ..labtalk_safe import labtalk_name
from .graph import annotate


@mcp.tool()
def prepare_spectrum_peaks(mz: list[float], intensity: list[float],
                           min_mz: float | None = None, max_mz: float | None = None,
                           normalization: str = 'none', labels: list[str] | None = None) -> str:
    """Prepare an explicitly selected peak table without changing Origin or source data.

    The arrays correspond row by row. Filters are inclusive. Normalization is
    none or max (divide selected intensities by their maximum); no implicit
    zero-fill or chemical assignment. Input order and source row numbers stay
    traceable. Supplied labels are copied verbatim as user-provided labels.
    """
    if not mz or len(mz)!=len(intensity) or len(mz)>100000 or (labels is not None and len(labels)!=len(mz)):
        raise ValueError('Provide equal nonempty arrays of at most 100000 peaks; labels must match.')
    if normalization not in {'none','max'}:
        raise ValueError('normalization must be none or max.')
    for bound in (min_mz,max_mz):
        if bound is not None and (isinstance(bound,bool) or not isinstance(bound,(int,float)) or not math.isfinite(bound)):
            raise ValueError('Bounds must be finite numbers.')
    if min_mz is not None and max_mz is not None and min_mz>max_mz:
        raise ValueError('min_mz must not exceed max_mz.')
    rows=[]
    for i,(x,y) in enumerate(zip(mz,intensity)):
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (x,y)):
            raise ValueError(f'Row {i+1} contains a nonfinite or nonnumeric value.')
        if x<0 or y<0:
            raise ValueError(f'Row {i+1} contains a negative mass or intensity.')
        if labels is not None and not isinstance(labels[i],str):
            raise ValueError(f'Row {i+1} has a non-text label.')
        if (min_mz is None or x>=min_mz) and (max_mz is None or x<=max_mz):
            rows.append({'source_row':i+1,'mz':x,'intensity':y,'label':labels[i] if labels is not None else None})
    if not rows: raise ValueError('No peaks remain after filtering.')
    denominator=None
    if normalization=='max':
        denominator=max(r['intensity'] for r in rows)
        if denominator<=0: raise ValueError('Maximum normalization requires a positive selected intensity.')
    for row in rows:
        row['plot_intensity']=row['intensity'] if denominator is None else row['intensity']/denominator
    return json.dumps({'peaks':rows,'normalization':normalization,'denominator':denominator,
                       'min_mz':min_mz,'max_mz':max_mz,'labels_source':'user' if labels is not None else None,
                       'zero_fill':False},ensure_ascii=False,allow_nan=False)


@mcp.tool()
def annotate_spectrum(graph_name: str, labels: list[dict], connectors: list[dict]) -> str:
    """Add explicitly supplied labels and peak connectors to graph layer 1.

    labels entries: {x, y, text}; connectors entries: {x1, y1, x2, y2}.
    Coordinates refer to graph data axes. Labels and pairings are caller-provided,
    not inferred chemical identities. May partly modify the graph on failure;
    inspect and save a project checkpoint before making changes to existing work.
    Visual checking is required for placement, clipping and object appearance.
    """
    name=labtalk_name(graph_name,'graph_name')
    if len(labels)+len(connectors)>100 or not (labels or connectors):
        raise ValueError('Provide 1-100 total labels and connectors.')
    for item in labels:
        if not isinstance(item,dict) or set(item)!={'x','y','text'} or not isinstance(item['text'],str) or not item['text'].strip() or any(c in item['text'] for c in ('"','\r','\n',';')):
            raise ValueError('Each label requires x, y and safe, nonempty text.')
        if any(isinstance(item[k],bool) or not isinstance(item[k],(int,float)) or not math.isfinite(item[k]) for k in ('x','y')):
            raise ValueError('Label coordinates must be finite numbers.')
    for item in connectors:
        if not isinstance(item,dict) or set(item)!={'x1','y1','x2','y2'} or any(isinstance(item[k],bool) or not isinstance(item[k],(int,float)) or not math.isfinite(item[k]) for k in ('x1','y1','x2','y2')):
            raise ValueError('Each connector requires four finite coordinates.')
    results=[]
    for item in labels:
        object_name='ms'+uuid.uuid4().hex[:10]
        try:
            result=annotate(name,'text',x1=item['x'],y1=item['y'],text=item['text'],name=object_name)
            results.append({'kind':'label','object_name':object_name,'request':item,'result':result})
        except Exception as exc:
            return json.dumps({'status':'partial','completed':results,'error':str(exc),'visual_inspection_required':True},ensure_ascii=False)
    for item in connectors:
        try:
            result=annotate(name,'line',**item)
            results.append({'kind':'connector','request':item,'result':result})
        except Exception as exc:
            return json.dumps({'status':'partial','completed':results,'error':str(exc),'visual_inspection_required':True},ensure_ascii=False)
    return json.dumps({'status':'applied','completed':results,'visual_inspection_required':True},ensure_ascii=False)
