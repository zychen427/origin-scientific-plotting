"""Validate the actual package and optionally draw a labelled native demo."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
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


async def main(args) -> None:
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'plugin_root': str(ROOT), 'static_validation': validate_files(),
              'demo_data': 'Synthetic data for plugin verification; not experimental measurements.',
              'calls': []}

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
            raise RuntimeError(f'{name}: {content}')
        return content

    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                report['server_info'] = initialized.serverInfo.model_dump()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                required = {'list_skills', 'get_skill', 'list_worksheets', 'create_worksheet',
                            'set_worksheet_data', 'create_graph', 'add_plot_to_graph',
                            'apply_publication_style', 'export_graph', 'save_project'}
                assert required <= names, sorted(required - names)
                report['tool_count'] = len(names)
                report['tools'] = sorted(names)
                await call(session, 'list_skills')
                skill = await call(session, 'get_skill', {'name': 'publication-figure'})
                (out / 'server_publication_skill.md').write_text(skill, encoding='utf-8')
                report['calls'][-1]['result'] = 'Full returned skill saved in server_publication_skill.md'
                report['initial_state'] = parse_object(await call(session, 'list_worksheets'))
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
                        'columns': json.dumps(columns), 'column_names': 'Index,Demo A,Demo B'})
                    graph = parse_object(await call(session, 'create_graph', {
                        'graph_name': 'PluginGraph' + suffix, 'data_book': book['name'],
                        'data_sheet': book['sheet'], 'x_col': 1, 'y_col': 2,
                        'plot_type': 'line+symbol', 'title': 'Plugin verification: synthetic data'}))
                    await call(session, 'add_plot_to_graph', {
                        'graph_name': graph['name'], 'data_book': book['name'],
                        'data_sheet': book['sheet'], 'x_col': 1, 'y_col': 3,
                        'plot_type': 'line+symbol'})
                    await call(session, 'apply_publication_style', {
                        'graph_name': graph['name'], 'x_label': 'Index (dimensionless)',
                        'y_label': 'Synthetic response (a.u.)', 'legend_entries': 'Demo A,Demo B',
                        'legend_position': 'top-left'})
                    stem = 'OriginPluginDemo_' + suffix
                    png = out / (stem + '.png')
                    project = out / (stem + '.opju')
                    await call(session, 'export_graph', {'graph_name': graph['name'],
                                                        'file_path': str(png), 'format': 'png', 'width': 1600})
                    await call(session, 'save_project', {'file_path': str(project)})
                    report['final_state'] = parse_object(await call(session, 'list_worksheets'))
                    assert graph['name'] in report['final_state']['graphs']
                    assert any(b['name'] == book['name'] for b in report['final_state']['workbooks'])
                    with Image.open(png) as image:
                        image.verify()
                    with Image.open(png) as image:
                        report['preview_size'] = list(image.size)
                        assert image.width == 1600
                    assert project.exists() and project.stat().st_size > 1000
                    report['artifacts'] = {kind: {'path': str(p), 'bytes': p.stat().st_size,
                        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                        for kind, p in [('preview', png), ('project', project)]}
                    report['native_plot_validation'] = 'passed'
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
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'verification')
    asyncio.run(main(parser.parse_args()))
