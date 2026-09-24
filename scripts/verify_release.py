"""Strict SHA-256 verification, including every setup-manifest entry."""
import hashlib
from pathlib import Path
import re
import sys
from release_audit import AuditError, safe_name, verify_setup


def verify(directory):
    directory = Path(directory).resolve()
    checksum_file = directory / 'SHA256SUMS.txt'
    if checksum_file.is_symlink():
        raise AuditError('Checksum manifest cannot be a symlink')
    lines = checksum_file.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise AuditError('Checksum manifest is empty')
    seen = set()
    for line in lines:
        match = re.fullmatch(r'([a-f0-9]{64})  (.+)', line)
        if not match:
            raise AuditError('Malformed checksum entry')
        expected, name = match.groups()
        safe_name(name)
        if '/' in name or name in seen or name == 'SHA256SUMS.txt':
            raise AuditError('Duplicate or unsafe release filename')
        seen.add(name)
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise AuditError(f'Missing or linked release file: {name}')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise AuditError(f'CHECKSUM MISMATCH: {name}')
        if name.endswith('-setup.zip'):
            verify_setup(data)
        print(f'OK {name}')
    return len(seen)


def main():
    try:
        verify(sys.argv[1] if len(sys.argv) > 1 else 'dist')
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))


if __name__ == '__main__':
    main()
