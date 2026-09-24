"""Verify downloaded release files using SHA256SUMS.txt in the same directory."""
import hashlib
from pathlib import Path
import sys


def main():
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist').resolve()
    for line in (directory / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        expected, name = line.split('  ', 1)
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file():
            raise SystemExit(f'Missing or unsafe release filename: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'CHECKSUM MISMATCH: {name}')
        print(f'OK {name}')


if __name__ == '__main__':
    main()
