"""Build an allowlisted setup ZIP and SHA-256 checksums after `uv build`."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('README.md', 'RELEASE.md', 'SECURITY.md', 'pyproject.toml', 'uv.lock', 'config.example.json',
         'install.ps1', 'install.sh', 'launch.ps1', 'launch.sh', '.python-version', '.gitattributes', '.gitignore', 'MANIFEST.in')
DIRS = ('src', 'docs', 'scripts', 'tests', '.github')


def collect(root=ROOT):
    files = [root / path for path in FILES if (root / path).is_file()]
    for directory in DIRS:
        files.extend(path for path in (root / directory).rglob('*')
                     if path.is_file() and path.suffix in {'.py', '.md', '.ps1', '.yml'}
                     and '__pycache__' not in path.parts and not any(p.endswith('.egg-info') for p in path.parts))
    return sorted(set(files))


def main():
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    module_version = re.search(r'__version__ = "([^"]+)"', (ROOT / 'src/quack_actual/__init__.py').read_text()).group(1)
    if version != module_version:
        raise SystemExit('Package and project versions differ')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    paths = collect()
    wheel = dist / f'quack_actual-{version}-py3-none-any.whl'
    if not wheel.is_file():
        raise SystemExit('Run uv build first; the application wheel is required')
    entries = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
    entries['wheel/' + wheel.name] = wheel.read_bytes()
    entries['FILE-MANIFEST.json'] = (json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}, indent=2) + '\n').encode()
    archive = dist / f'quack-actual-{version}-setup.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, data in sorted(entries.items()):
            entry = zipfile.ZipInfo(f'quack-actual-{version}/{name}', (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | (0o755 if name.endswith('.sh') else 0o644)) << 16
            output.writestr(entry, data)
    artifacts = sorted(path for path in dist.iterdir() if path.suffix in {'.zip', '.whl', '.gz'})
    (dist / 'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts), encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    main()
