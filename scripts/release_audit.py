"""Offline release hygiene checks. No user identifiers are stored in the policy.

Optional private terms: QUACK_ACTUAL_AUDIT_TERMS_JSON='["term", "another term"]'.
Matches report categories and filenames, never the matched secret/identifier.
These checks are regression guards, not a guarantee of anonymity or safety.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 64 * 1024 * 1024
REQUIRED = {'pyproject.toml', 'uv.lock', 'README.md', 'install.ps1', 'install.sh',
            'launch.ps1', 'launch.sh', 'RELEASE-FILES.txt'}
PATTERNS = {
    'named home-directory path': re.compile(rb'(?:/home/|/Users/|[A-Za-z]:[\\/]+Users[\\/]+|/mnt/[a-z]/Users/)[A-Za-z0-9_.-]+', re.I),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential-shaped value': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{32,})'),
}


class AuditError(ValueError):
    """An artifact did not meet the release policy."""


def safe_name(name):
    if not isinstance(name, str) or not name or any(c in name for c in ('\\', ':', '\x00', '\r', '\n')):
        raise AuditError('Invalid archive or manifest path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'.', '..', ''} for p in name.split('/')):
        raise AuditError('Non-relative archive or manifest path')
    return name


def private_terms():
    terms = json.loads(os.environ.get('QUACK_ACTUAL_AUDIT_TERMS_JSON', '[]'))
    if not isinstance(terms, list) or any(not isinstance(t, str) or not t.strip() for t in terms):
        raise AuditError('Private audit terms must be a JSON array of nonempty strings')
    return [t.casefold() for t in terms]


def scan(entries):
    terms = private_terms()
    findings = []
    for name, data in entries.items():
        safe_name(name)
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                findings.append(f'{name}: {label}')
        if terms:
            text = (name + '\n' + data.decode('utf-8', errors='replace')).casefold()
            if any(term in text for term in terms):
                findings.append(f'{name}: private audit-term match')
    if findings:
        raise AuditError('\n'.join(findings))


def source_entries(root=ROOT):
    root = Path(root).resolve()
    manifest = root / 'RELEASE-FILES.txt'
    if manifest.is_symlink() or not manifest.is_file():
        raise AuditError('A regular RELEASE-FILES.txt is required')
    names = [line.strip() for line in manifest.read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if len(names) != len(set(names)) or not REQUIRED.issubset(names):
        raise AuditError('Release allowlist has duplicates or is missing required files')
    entries = {}
    for name in names:
        safe_name(name)
        parts = PurePosixPath(name).parts
        if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
            raise AuditError(f'{name}: symlinks cannot be shipped')
        file = root / name
        if not file.is_file() or not file.resolve().is_relative_to(root):
            raise AuditError(f'{name}: required release file is missing or outside the source tree')
        entries[name] = file.read_bytes()
    scan(entries)
    lock = tomllib.loads(entries['uv.lock'].decode('utf-8'))
    for package in lock.get('package', []):
        source = package.get('source', {})
        if source == {'editable': '.'} and package['name'] == 'quack-actual':
            continue
        if source != {'registry': 'https://pypi.org/simple'}:
            raise AuditError('Lockfile contains a non-public or machine-local dependency source')
    return entries


def zip_entries(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        result, seen, total = {}, set(), 0
        for entry in archive.infolist():
            name = safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            if name in seen:
                raise AuditError('Duplicate ZIP entry')
            seen.add(name)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if entry.flag_bits & 1 or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise AuditError('Encrypted files, symlinks and special ZIP entries are not allowed')
            total += entry.file_size
            if total > LIMIT or len(seen) > 4096:
                raise AuditError('Archive exceeds review limits')
            if not entry.is_dir():
                result[name] = archive.read(entry)
        return result


def wheel_entries(data, source):
    entries = zip_entries(data)
    expected = {name.removeprefix('src/'): value for name, value in source.items()
                if name.startswith('src/quack_actual/')}
    version = tomllib.loads(source['pyproject.toml'].decode())['project']['version']
    info = f'quack_actual-{version}.dist-info/'
    metadata = {info + name for name in ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt')}
    if set(entries) != set(expected) | metadata:
        raise AuditError('Wheel has unexpected or missing package/metadata files')
    if any(entries[name] != value for name, value in expected.items()):
        raise AuditError('Wheel source differs from the release source; rebuild the wheel')
    headers = BytesParser().parsebytes(entries[info + 'METADATA'], headersonly=True)
    if any(headers.get(field) for field in ('Author', 'Author-email', 'Maintainer', 'Maintainer-email')):
        raise AuditError('Wheel metadata contains author/maintainer identity fields')
    scan(entries)
    return entries


def sdist_entries(data, source):
    version = tomllib.loads(source['pyproject.toml'].decode())['project']['version']
    prefix = f'quack_actual-{version}/'
    generated = {'PKG-INFO', 'setup.cfg'} | {
        'src/quack_actual.egg-info/' + name for name in
        ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'requires.txt', 'top_level.txt')}
    entries, seen, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            safe_name(member.name.rstrip('/'))
            if member.name in seen:
                raise AuditError('Duplicate source archive entry')
            seen.add(member.name)
            if not member.isdir() and not member.isfile():
                raise AuditError('Source archive contains links or special files')
            total += member.size
            if total > LIMIT or len(seen) > 4096:
                raise AuditError('Source archive exceeds review limits')
            if member.isdir():
                continue
            if not member.name.startswith(prefix):
                raise AuditError('Unexpected source archive root')
            name = member.name[len(prefix):]
            if name not in source and name not in generated:
                raise AuditError(f'{name}: unapproved source archive member')
            entries[name] = archive.extractfile(member).read()
    if any(entries.get(name) != value for name, value in source.items()):
        raise AuditError('Source distribution omits or differs from release source')
    scan(entries)
    return entries


def verify_setup(data):
    entries = zip_entries(data)
    roots = {name.split('/')[0] for name in entries}
    if len(roots) != 1:
        raise AuditError('Setup ZIP must have exactly one root directory')
    prefix = roots.pop() + '/'
    entries = {name.removeprefix(prefix): value for name, value in entries.items()}
    raw = entries.pop('FILE-MANIFEST.json', None)
    if raw is None:
        raise AuditError('Setup ZIP is missing FILE-MANIFEST.json')
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or set(manifest) != set(entries):
        raise AuditError('Setup ZIP manifest has unexpected or missing files')
    for name, expected in manifest.items():
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise AuditError('Invalid manifest digest')
        if hashlib.sha256(entries[name]).hexdigest() != expected:
            raise AuditError(f'{name}: manifest checksum mismatch')
    wheels = [name for name in entries if name.startswith('wheel/') and name.endswith('.whl')]
    if len(wheels) != 1:
        raise AuditError('Setup ZIP requires one application wheel')
    source = {name: value for name, value in entries.items() if name != wheels[0]}
    scan(source)
    wheel_entries(entries[wheels[0]], source)
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    entries = source_entries(args.root)
    print(f'Release hygiene passed for {len(entries)} allowlisted source files.')
    if not any(name.upper().startswith('LICENSE') for name in entries):
        print('NOTICE: No project license is selected; this is not open-source licensing clearance.')


if __name__ == '__main__':
    try:
        main()
    except (AuditError, OSError, ValueError) as exc:
        raise SystemExit(str(exc))
