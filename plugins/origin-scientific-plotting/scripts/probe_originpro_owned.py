"""Cold-start originpro probe with synthetic data; never attaches existing Origin."""
import json
import os
import time
import traceback
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server' / 'src'))
from origin_pro_mcp.daemon import _origin_process_pids
from origin_pro_mcp.existing_origin import _process_identity

out = ROOT / ('verification_originpro_owned_' + str(os.getpid()))
out.mkdir(exist_ok=True)
result = {'before': sorted(_origin_process_pids()), 'operations': {}, 'closed': False}
if result['before']:
    raise RuntimeError('This synthetic probe requires a cold start.')
identity = None
op = None
try:
    import originpro as op
    op.set_show(True)
    op.lt_exec('run.python("import os,PyOrigin; PyOrigin.LT_set_var(\'__probe_owned_pid\',os.getpid())",0);')
    pid = int(op.lt_int('__probe_owned_pid'))
    if pid in result['before'] or pid not in _origin_process_pids():
        raise RuntimeError('originpro peer is not a newly created Origin process')
    identity = _process_identity(pid)
    if Path(identity['image']).name.lower() not in ('origin.exe', 'origin64.exe'):
        raise RuntimeError('Unexpected Origin process image')
    result['identity'] = identity
    import win32com.client
    from origin_pro_mcp.existing_origin import query_peer_pid
    fallback = win32com.client.Dispatch('Origin.ApplicationSI')
    fallback_pid = query_peer_pid(fallback)
    result['fallback_pid'] = fallback_pid
    if fallback_pid != pid:
        raise RuntimeError('COM fallback selected a different Origin; no fallback operation attempted')
    fallback = None
    w = op.new_sheet('w', 'OwnedProbe')
    result['operations']['new_sheet'] = 'passed'
    w.from_list(0, [0, 1, 2, 3], lname='X')
    w.from_list(1, [1, 3, 5, 7], lname='Y')
    assert w.to_list(1) == [1, 3, 5, 7]
    result['operations']['write_read'] = 'passed'
    g = op.new_graph('OwnedProbeGraph')
    layer = g[0]
    layer.add_plot(w, 1, 0, type='y')
    assert len(layer.plot_list()) == 1
    layer.rescale()
    result['operations']['graph'] = 'passed'
    result['operations']['save'] = bool(op.save(str(out / 'probe.opju')))
    result['operations']['export'] = str(g.save_fig(str(out / 'probe.png'), type='png', replace=False, width=900))
except Exception as exc:
    result['error'] = f'{type(exc).__name__}: {exc}'
    result['traceback'] = traceback.format_exc()
finally:
    if identity and op:
        try:
            # Save the synthetic project before asking Origin to exit.
            result['cleanup_save'] = bool(op.save(str(out / 'cleanup.opju')))
            if _process_identity(identity['pid']) != identity:
                raise RuntimeError('process identity changed')
            op.exit()
            for _ in range(40):
                if identity['pid'] not in _origin_process_pids():
                    result['closed'] = True
                    break
                time.sleep(.25)
        except Exception as exc:
            result['cleanup_error'] = f'{type(exc).__name__}: {exc}'
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
