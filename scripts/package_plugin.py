"""Package the current plugin, sync the standalone Skill, and hash all distribution files."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/origin-scientific-plotting'
EXCLUDE = {'.git', '.venv', '__pycache__', '.local-config', 'verification', '.pytest_cache'}


def distribution_files():
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if path.is_file() and not EXCLUDE.intersection(rel.parts) and path.suffix != '.pyc' and rel.as_posix() != 'SHA256SUMS.json':
            yield path


def main():
    manifest = json.loads((PLUGIN / 'plugin.json').read_text(encoding='utf-8'))
    assert manifest['name'] == PLUGIN.name
    for path in (PLUGIN / 'skills/origin-plotting').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            target = ROOT / 'skills/origin-plotting' / path.relative_to(PLUGIN / 'skills/origin-plotting')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    output = ROOT / 'packages' / (manifest['name'] + '-' + manifest['version'] + '.zip')
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PLUGIN.rglob('*')):
            if path.is_file() and not EXCLUDE.intersection(path.relative_to(PLUGIN).parts) and path.suffix != '.pyc':
                archive.write(path, (Path(PLUGIN.name) / path.relative_to(PLUGIN)).as_posix())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in distribution_files()}
    (ROOT / 'SHA256SUMS.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'archive': str(output), 'files': len(hashes)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
