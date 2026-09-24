"""Build a reviewed setup ZIP and normalized sdist after `uv build`."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import tarfile
import tomllib
import zipfile
from release_audit import ROOT, AuditError, source_entries, wheel_entries, sdist_entries, verify_setup


def collect(root=ROOT):
    """Only explicitly reviewed files; required files and symlinks fail closed."""
    return [Path(root) / name for name in sorted(source_entries(root))]


def normalize_sdist(data):
    """Remove build-host owner names, IDs, timestamps and PAX metadata."""
    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as source:
        with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as target:
                for member in sorted(source.getmembers(), key=lambda m: m.name):
                    if not member.isdir() and not member.isfile():
                        raise AuditError('Source archive contains links or special files')
                    payload = source.extractfile(member) if member.isfile() else None
                    info = tarfile.TarInfo(member.name)
                    info.type, info.size = member.type, member.size
                    info.mode = 0o755 if member.isdir() or member.name.endswith('.sh') else 0o644
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    target.addfile(info, payload)
    return output.getvalue()


def main():
    entries = source_entries(ROOT)
    version = tomllib.loads(entries['pyproject.toml'].decode('utf-8'))['project']['version']
    module_version = re.search(r'__version__ = "([^"]+)"', entries['src/quack_actual/__init__.py'].decode()).group(1)
    if version != module_version:
        raise AuditError('Package and project versions differ')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    wheel = dist / f'quack_actual-{version}-py3-none-any.whl'
    sdist = dist / f'quack_actual-{version}.tar.gz'
    archive = dist / f'quack-actual-{version}-setup.zip'
    artifacts = (archive, wheel, sdist)
    # Do not silently include old/unrelated archives in a release checksum list.
    if any(path.suffix in {'.zip', '.whl', '.gz'} and path not in artifacts for path in dist.iterdir()):
        raise AuditError('dist contains unrelated archives; use a clean release output directory')
    if not wheel.is_file() or not sdist.is_file() or wheel.is_symlink() or sdist.is_symlink():
        raise AuditError('Run uv build first; regular wheel and source distribution files are required')
    wheel_entries(wheel.read_bytes(), entries)
    sdist_entries(sdist.read_bytes(), entries)
    sdist.write_bytes(normalize_sdist(sdist.read_bytes()))
    entries['wheel/' + wheel.name] = wheel.read_bytes()
    entries['FILE-MANIFEST.json'] = (json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}, indent=2) + '\n').encode()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, data in sorted(entries.items()):
            entry = zipfile.ZipInfo(f'quack-actual-{version}/{name}', (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | (0o755 if name.endswith('.sh') else 0o644)) << 16
            output.writestr(entry, data)
    verify_setup(archive.read_bytes())
    (dist / 'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts), encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    try:
        main()
    except (AuditError, OSError, ValueError) as exc:
        raise SystemExit(str(exc))
