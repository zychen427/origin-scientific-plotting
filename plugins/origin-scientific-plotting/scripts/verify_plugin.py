"""Validate the actual package and optionally draw a labelled native demo."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def validate_files() -> dict:
    manifest = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))
    compat = json.loads((ROOT / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    config = json.loads((ROOT / 'mcp.json').read_text(encoding='utf-8'))
    assert manifest['name'] == compat['name'] == 'origin-scientific-plotting'
    assert manifest['version'] == compat['version']
    interface = manifest['extensions']['com.openai']['interface']
    assert interface == compat['interface']
    assert len(interface['shortDescription']) <= 30
    assert set(manifest).isdisjoint({'skills', 'mcpServers', 'apps', 'interface'})
    assert len(config['mcpServers']) == 1
    for field in ('logo', 'composerIcon'):
        dest = (ROOT / interface[field]).resolve()
        assert dest.is_relative_to(ROOT.resolve()) and dest.is_file()
        assert dest.stat().st_size <= 5 * 1024 * 1024
        with Image.open(dest) as img:
            assert img.width == img.height and 48 <= img.width <= 4096
    provenance = json.loads((ROOT / 'server/PROVENANCE.json').read_text(encoding='utf-8'))
    for name, expected in provenance['source_files_sha256'].items():
        assert hashlib.sha256((ROOT / 'server/src' / name).read_bytes()).hexdigest() == expected, name
    skill = (ROOT / 'skills/origin-plotting/SKILL.md').read_text(encoding='utf-8')
    assert skill.startswith('---\nname: origin-plotting\ndescription: ')
    return {'manifest': 'passed', 'compatibility': 'passed', 'icon': 'passed',
            'source_hashes': 'passed', 'source_file_count': len(provenance['source_files_sha256'])}


def run_integration_tests() -> dict:
    """Run the opt-in cross-version/pool/spawn-race integration suite.

    Isolated: temporary lockfiles + fake Origin; never touches the user's daemon
    or Origin GUI. Skipped-by-default behaviour of the plain verification is
    unchanged.
    """
    env = os.environ.copy()
    env['ORIGIN_PRO_MCP_INTEGRATION'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    tests_dir = ROOT / 'server' / 'src' / 'tests'
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover',
             '-s', str(tests_dir), '-p', 'test_integration.py'],
            cwd=str(ROOT / 'server' / 'src'), env=env,
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'failed', 'returncode': None,
                'tail': f'{type(exc).__name__}: {exc}'}
    output = (proc.stdout or '') + (proc.stderr or '')
    return {
        'status': 'passed' if proc.returncode == 0 else 'failed',
        'returncode': proc.returncode,
        'tail': output[-4000:],
    }


async def main(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'plugin_root': str(ROOT), 'static_validation': validate_files(),
              'demo_data': 'Synthetic data for plugin verification; not experimental measurements.',
              'calls': []}
    if args.static_only:
        report['status'] = 'static_passed'
        (out / 'verification.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'calls'},
                         ensure_ascii=False, indent=2))
        return

    def parse_object(text):
        stripped = text.lstrip()
        obj, end = json.JSONDecoder().raw_decode(stripped)
        tail = stripped[end:].strip()
        if tail:
            if not tail.startswith('[origin-mcp] Note:'):
                raise ValueError('Unexpected text following the JSON result: ' + tail)
            report.setdefault('session_notes', []).append(tail)
        if not isinstance(obj, dict):
            raise ValueError('Expected a JSON object from the Origin tool.')
        return obj
    config = json.loads((ROOT / 'mcp.json').read_text(encoding='utf-8'))
    spec = next(iter(config['mcpServers'].values()))
    env = os.environ.copy()
    env.update(spec.get('env', {}))
    env['ORIGIN_PRO_MCP_BACKEND'] = 'originpro' if args.originpro else 'com'
    if args.lockfile is not None:
        lockfile = args.lockfile.resolve()
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        env['ORIGIN_PRO_MCP_LOCKFILE'] = str(lockfile)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    params = StdioServerParameters(
        command=spec['command'],
        args=[a.replace('${PLUGIN_ROOT}', str(ROOT)) for a in spec['args']],
        env=env, cwd=spec.get('cwd', str(ROOT)).replace('${PLUGIN_ROOT}', str(ROOT)),
    )

    async def call(session, name, data=None):
        result = await session.call_tool(name, data or {})
        content = '\n'.join(getattr(c, 'text', '') for c in result.content)
        report['calls'].append({'tool': name, 'arguments': data or {}, 'is_error': result.isError,
                                'result': content})
        if result.isError:
            if (report.get('project_mutated') and not report.get('failure_cleanup_attempted')
                    and name not in {'save_project_checkpoint', 'release_origin_session'}):
                report['failure_cleanup_attempted'] = True
                failure_checkpoint = out / f"failed_partial_{len(report['calls'])}.opju"
                try:
                    await call(session, 'save_project',
                               {'file_path': str(failure_checkpoint)})
                    if failure_checkpoint.exists():
                        report['failure_checkpoint'] = str(failure_checkpoint)
                except BaseException as checkpoint_exc:
                    report['failure_checkpoint_error'] = (
                        f'{type(checkpoint_exc).__name__}: {checkpoint_exc}')
                try:
                    await call(session, 'release_origin_session')
                    report['session_release_after_failure'] = 'passed'
                except BaseException as release_exc:
                    report['session_release_after_failure'] = (
                        f'failed: {type(release_exc).__name__}: {release_exc}')
            raise RuntimeError(f'{name}: {content}')
        return content

    async def expect_error(session, name, data, expected):
        result = await session.call_tool(name, data or {})
        content = '\n'.join(getattr(c, 'text', '') for c in result.content)
        report['calls'].append({'tool': name, 'arguments': data or {},
                                'is_error': result.isError, 'result': content})
        if not result.isError or expected not in content:
            raise AssertionError(f'{name} did not return the expected actionable error: {content}')
        return content

    try:
        sys.path.insert(0, str(ROOT / 'server/src'))
        from origin_pro_mcp.daemon import _origin_process_pids
        report['origin_pids_before'] = sorted(_origin_process_pids())
        if args.require_cold and report['origin_pids_before']:
            raise RuntimeError('Cold-start verification requires no running Origin process.')
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                try:
                    initialized = await session.initialize()
                    server_info = getattr(initialized, 'serverInfo', None)
                    if server_info is None:
                        server_info = getattr(initialized, 'server_info', None)
                    if server_info is None:
                        raise RuntimeError('MCP initialize response does not include serverInfo/server_info.')
                    report['server_info'] = server_info.model_dump()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    required = {'list_skills', 'get_skill', 'list_worksheets', 'create_worksheet',
                                'set_worksheet_data', 'create_graph', 'add_plot_to_graph',
                                'apply_publication_style', 'export_graph', 'save_project'}
                    assert required <= names, sorted(required - names)
                    report['tool_count'] = len(names)
                    report['tools'] = sorted(names)
                    if args.existing_pid is not None:
                        connected = parse_object(await call(session, 'connect_existing_origin',
                                                            {'pid': args.existing_pid}))
                        report['existing_origin_target'] = connected
                        checkpoint = out / f'OriginCheckpoint_PID{args.existing_pid}.opju'
                        await call(session, 'save_project', {'file_path': str(checkpoint)})
                        report['pre_edit_checkpoint'] = str(checkpoint)
                    await call(session, 'list_skills')
                    await call(session, 'get_skill', {'name': 'plot-preflight'})
                    skill = await call(session, 'get_skill', {'name': 'publication-figure'})
                    (out / 'server_publication_skill.md').write_text(skill, encoding='utf-8')
                    report['calls'][-1]['result'] = 'Full returned skill saved in server_publication_skill.md'
                    report['initial_state'] = parse_object(await call(session, 'list_worksheets'))
                    diagnostic = parse_object(await call(session, 'diagnose_origin_runtime'))
                    assert diagnostic['control_path']['transport'] in ('COM', 'OriginExt COM')
                    assert diagnostic['originpro_backend']['available'] is args.originpro
                    assert diagnostic['originpro_backend']['enabled'] is args.originpro
                    expected_mode = 'attached_shared' if args.existing_pid is not None else 'isolated'
                    assert diagnostic['control_path']['mode'] == expected_mode
                    assert diagnostic['control_path']['uses_physical_mouse_or_keyboard'] is False
                    report['control_path'] = diagnostic['control_path']
                    report['session_identity'] = diagnostic['session']
                    if args.existing_pid is None:
                        assert diagnostic['session']['origin_pid'] not in report['origin_pids_before']
                        assert diagnostic['window_identity_verified'] is True
                    probe = parse_object(await call(session, 'run_labtalk', {'script': '_opm_verify_route=314;', 'capture': ['_opm_verify_route']}))
                    assert probe['status'] == 'ok' and probe['values']['_opm_verify_route'] == 314
                    report['com_labtalk_roundtrip'] = 'passed'
                    report['protocol_validation'] = 'passed'
                    if args.plot:
                        suffix = uuid.uuid4().hex[:6]
                        book = parse_object(await call(session, 'create_worksheet',
                                                     {'book_name': 'PluginDemo' + suffix, 'sheet_name': 'DemoData'}))
                        columns = [[0, 1, 2, 3, 4, 5, 6, 7, 8],
                                   [0.4, 0.7, 1.2, 1.7, 2.1, 2.7, 3.0, 3.6, 4.1],
                                   [0.6, 0.9, 1.0, 1.5, 1.9, 2.0, 2.5, 2.9, 3.2]]
                        await call(session, 'set_worksheet_data', {
                            'book_name': book['name'], 'sheet_name': book['sheet'],
                            'columns': json.dumps(columns), 'column_names': '时间,浓度甲,浓度乙'})
                        report['project_mutated'] = True
                        readback = parse_object(await call(session, 'get_worksheet_data', {
                            'book_name': book['name'], 'sheet_name': book['sheet']}))
                        assert readback['columns'][:3] == columns
                        report['worksheet_roundtrip'] = '27 synthetic values matched'
                        csv_output = out / ('roundtrip_' + suffix + '.csv')
                        await call(session, 'export_worksheet', {'book_name': book['name'],
                            'sheet_name': book['sheet'], 'file_path': str(csv_output)})
                        import csv
                        with csv_output.open(encoding='utf-8-sig', newline='') as stream:
                            csv_rows = list(csv.reader(stream))
                        assert len(csv_rows) == 10 and len(csv_rows[0]) == 3
                        assert [[float(row[i]) for row in csv_rows[1:]] for i in range(3)] == columns
                        report['csv_export_readback'] = '27 synthetic values matched'
                        await expect_error(session, 'release_origin_session', {}, 'unsaved changes')
                        report['unsaved_release_guard'] = 'passed; connection retained for drawing'
                        graph = parse_object(await call(session, 'create_graph', {
                            'graph_name': 'PluginGraph' + suffix, 'data_book': book['name'],
                            'data_sheet': book['sheet'], 'x_col': 1, 'y_col': 2,
                            'plot_type': 'line+symbol', 'title': 'Plugin verification: synthetic data'}))
                        await call(session, 'add_plot_to_graph', {
                            'graph_name': graph['name'], 'data_book': book['name'],
                            'data_sheet': book['sheet'], 'x_col': 1, 'y_col': 3,
                            'plot_type': 'line+symbol'})
                        await call(session, 'apply_publication_style', {
                            'graph_name': graph['name'], 'x_label': '时间 Time (s)',
                            'y_label': '浓度 Concentration (a.u.)', 'legend_position': 'top-left'})
                        await call(session, 'set_plot_style', {
                            'graph_name': graph['name'], 'plot_index': 1,
                            'line_width': 2.0, 'symbol_size': 8})
                        layers = parse_object(await call(session, 'inspect_graph_layers', {
                            'graph_name': graph['name']}))
                        assert layers['layer_count'] == 1
                        assert len(layers['layers'][0]['plots']) == 2
                        report['editable_graph_layers'] = layers
                        fit_csv = out / ('OriginMCPFit_' + suffix + '.csv')
                        fit_csv.write_text('X,Y\n0,1\n1,3\n2,5\n3,7\n4,9\n', encoding='utf-8')
                        imported = parse_object(await call(session, 'import_data', {
                            'file_path': str(fit_csv), 'format': 'csv',
                            'book_name': 'MCPImport' + suffix}))
                        imported_state = parse_object(await call(session, 'list_worksheets'))
                        imported_book = next((b for b in imported_state['workbooks']
                                              if b['name'] == imported['name']), None)
                        if imported_book is None or not imported_book.get('sheets'):
                            raise AssertionError(f"Imported workbook {imported['name']!r} has no readable worksheet.")
                        fit_sheet = imported_book['sheets'][0]
                        imported_values = parse_object(await call(session, 'get_worksheet_data', {
                            'book_name': imported['name'], 'sheet_name': fit_sheet}))
                        assert imported_values['columns'][:2] == [[0,1,2,3,4],[1,3,5,7,9]]
                        report['csv_roundtrip'] = '10 synthetic values matched'
                        fit = parse_object(await call(session, 'curve_fit', {
                            'data_book': imported['name'], 'data_sheet': fit_sheet,
                            'x_col': 1, 'y_col': 2, 'function': 'line'}))
                        assert abs(fit['parameters']['slope']['value'] - 2.0) < 1e-8
                        assert abs(fit['parameters']['intercept']['value'] - 1.0) < 1e-8
                        report['linear_fit'] = fit
                        await expect_error(session, 'curve_fit', {
                            'data_book': imported['name'], 'data_sheet': fit_sheet,
                            'x_col': 0, 'y_col': 2, 'function': 'line'}, 'x_col')
                        report['invalid_fit_parameters'] = 'rejected before Origin mutation'
                        labels = parse_object(await call(session, 'run_labtalk', {'script': '_opm_x$=xb.text$; _opm_y$=yl.text$;', 'capture': ['_opm_x$', '_opm_y$'], 'window': graph['name']}))
                        assert r'\b(' in labels['values']['_opm_x$'] and r'\f:' in labels['values']['_opm_x$'] and ('SimSun' in labels['values']['_opm_x$'] or '宋体' in labels['values']['_opm_x$'])
                        assert r'\b(' in labels['values']['_opm_y$'] and r'\f:' in labels['values']['_opm_y$'] and ('SimSun' in labels['values']['_opm_y$'] or '宋体' in labels['values']['_opm_y$'])
                        report['mixed_axis_format_readback'] = labels['values']
                        stem = 'OriginPluginDemo_' + suffix
                        png = out / (stem + '.png')
                        project = out / (stem + '.opju')
                        pdf = out / (stem + '.pdf')
                        await call(session, 'export_graph', {'graph_name': graph['name'],
                                                            'file_path': str(png), 'format': 'png', 'width': 1600})
                        await call(session, 'export_graph', {'graph_name': graph['name'],
                                                            'file_path': str(pdf), 'format': 'pdf'})
                        report['pdf'] = str(pdf)
                        await call(session, 'save_project', {'file_path': str(project)})
                        report['final_state'] = parse_object(await call(session, 'list_worksheets'))
                        assert graph['name'] in report['final_state']['graphs']
                        assert any(b['name'] == book['name'] for b in report['final_state']['workbooks'])
                        await call(session, 'load_project', {
                            'file_path': str(project), 'replace_current': True})
                        reopened = parse_object(await call(session, 'get_worksheet_data', {
                            'book_name': book['name'], 'sheet_name': book['sheet']}))
                        assert reopened['columns'][:3] == columns
                        reopened_layers = parse_object(await call(session, 'inspect_graph_layers', {
                            'graph_name': graph['name']}))
                        assert reopened_layers['layer_count'] == 1
                        assert len(reopened_layers['layers'][0]['plots']) == 2
                        report['project_reopen'] = 'passed: all 27 values and 2 editable curves'
                        # Inspection activates windows; save any resulting page state
                        # before releasing the COM server.
                        await call(session, 'save_project', {'file_path': str(project)})
                        with Image.open(png) as image:
                            image.verify()
                        with Image.open(png) as image:
                            report['preview_size'] = list(image.size)
                            assert image.width == 1600
                        assert project.exists() and project.stat().st_size > 1000
                        report['artifacts'] = {kind: {'path': str(p), 'bytes': p.stat().st_size,
                            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                            for kind, p in [('preview', png), ('project', project), ('pdf', pdf)]}
                        report['native_plot_validation'] = 'passed'
                    await call(session, 'release_origin_session')
                    report['session_release'] = 'passed'
                except BaseException:
                    if args.existing_pid is None and report.get('project_mutated') and not report.get('failure_cleanup_attempted'):
                        report['failure_cleanup_attempted'] = True
                        try:
                            checkpoint = out / 'failure_recovery.opju'
                            saved = await session.call_tool('save_project', {'file_path': str(checkpoint)})
                            report['failure_recovery_save'] = {'error': saved.isError, 'result': str(saved.content)}
                            if not saved.isError:
                                released = await session.call_tool('release_origin_session', {})
                                report['failure_recovery_release'] = {'error': released.isError, 'result': str(released.content)}
                        except BaseException as cleanup_exc:
                            report['failure_cleanup_error'] = repr(cleanup_exc)
                    raise
        if args.close_test_origin:
            if args.existing_pid is not None or not args.plot:
                raise RuntimeError('--close-test-origin requires an isolated synthetic --plot run.')
            from origin_pro_mcp.existing_origin import _process_identity, require_window
            identity = report['session_identity']['origin_process']
            target_pid = identity['pid']
            current = _process_identity(target_pid)
            assert current == identity, 'Process identity changed before close.'
            window = require_window(target_pid)
            assert window['creation_filetime'] == identity['creation_filetime']
            import win32api, win32con, win32event, win32gui
            handle = win32api.OpenProcess(0x00100000, False, target_pid)
            try:
                win32gui.PostMessage(window['hwnd'], win32con.WM_CLOSE, 0, 0)
                closed = win32event.WaitForSingleObject(handle, 10000) == win32event.WAIT_OBJECT_0
            finally:
                handle.Close()
            report['normal_window_close'] = {'pid': target_pid, 'exited': closed,
                                            'forced_termination': False}
            assert closed, 'Saved test Origin did not exit after normal WM_CLOSE.'
        report['origin_pids_after'] = sorted(_origin_process_pids())
        if args.integration:
            report['integration'] = run_integration_tests()
            if report['integration']['status'] != 'passed':
                raise RuntimeError('integration tests failed: '
                                   + report['integration']['tail'])
        report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'
        report['error'] = repr(exc)
        raise
    finally:
        (out / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        compact = {k: v for k, v in report.items() if k not in {'calls', 'tools'}}
        print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plot', action='store_true', help='Create and export explicitly synthetic demo data.')
    parser.add_argument('--originpro', action='store_true', help='Use the experimental isolated native originpro backend.')
    parser.add_argument('--static-only', action='store_true',
                        help='Validate manifests, assets and source hashes without launching Origin.')
    parser.add_argument('--existing-pid', type=int,
                        help='Use only the visible Origin process with this PID; refuses mismatches.')
    parser.add_argument('--lockfile', type=Path,
                        help='Use a dedicated daemon lockfile for an isolated verification run.')
    parser.add_argument('--require-cold', action='store_true',
                        help='Refuse unless no Origin processes exist before MCP starts.')
    parser.add_argument('--close-test-origin', action='store_true',
                        help='After saving and releasing an isolated synthetic plot run, close its exact verified window normally.')
    parser.add_argument('--integration', action='store_true',
                        help='Also run the isolated cross-version/pool/spawn-race suite.')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'verification')
    asyncio.run(main(parser.parse_args()))
