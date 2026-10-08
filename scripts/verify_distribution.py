"""Check hashes, both Skill copies, original source files and the packaged ZIP."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/origin-scientific-plotting'


def main():
    hashes = json.loads((ROOT / 'SHA256SUMS.json').read_text(encoding='utf-8'))
    for rel, expected in hashes.items():
        target = (ROOT / rel).resolve()
        assert target.is_relative_to(ROOT.resolve()), rel
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected, rel
    for path in (PLUGIN / 'skills/origin-plotting').rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (ROOT / 'skills/origin-plotting' / path.relative_to(PLUGIN / 'skills/origin-plotting')).read_bytes()
    provenance = json.loads((PLUGIN / 'server/PROVENANCE.json').read_text(encoding='utf-8'))
    for rel, expected in provenance['source_files_sha256'].items():
        assert hashlib.sha256((PLUGIN / 'server/src' / rel).read_bytes()).hexdigest() == expected, rel
    manifest = json.loads((PLUGIN / 'plugin.json').read_text(encoding='utf-8'))
    archive_path = ROOT / 'packages' / (manifest['name'] + '-' + manifest['version'] + '.zip')
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        members = set(archive.namelist())
        expected_members = set()
        for path in PLUGIN.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                name = (Path(PLUGIN.name) / path.relative_to(PLUGIN)).as_posix()
                expected_members.add(name)
                assert archive.read(name) == path.read_bytes(), name
        assert members == expected_members
    print(json.dumps({'status': 'passed', 'distribution_files': len(hashes),
                      'source_files': len(provenance['source_files_sha256']), 'archive_files': len(members)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
